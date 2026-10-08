import { appendFile, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type {
  PostToolUseFailureHookInput,
  PostToolUseHookInput,
} from "@anthropic-ai/claude-agent-sdk";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MemoryWatchdogKillReader } from "../../../server/memory-watchdog";
import { Logger } from "../../../utils/logger";
import { createMemoryKillNoticeHook } from "./memory-kill-hook";
import { VALIDATION_LOCK_PREFIX } from "./memory-validation";

const GIB = 1024 ** 3;
const STARTED_AT_SECONDS = 1_800_000_000;

function killRecord(pid: number, ts: number): string {
  return JSON.stringify({
    event: "kill",
    ts,
    pid,
    comm: "bash",
    tree_rss: 22 * GIB,
    current: 27 * GIB,
    limit: 32 * GIB,
    signal: "SIGKILL",
  });
}

function shellInput(
  hookEventName: "PostToolUse" | "PostToolUseFailure",
  toolName = "Bash",
  error = "Exit code 137",
): PostToolUseHookInput | PostToolUseFailureHookInput {
  const input = {
    session_id: "s",
    transcript_path: "/tmp/t",
    cwd: "/tmp",
    tool_name: toolName,
    tool_input: { command: "pnpm test" },
    tool_use_id: "toolu_1",
  };
  return hookEventName === "PostToolUse"
    ? { ...input, hook_event_name: hookEventName, tool_response: "" }
    : { ...input, hook_event_name: hookEventName, error };
}

type HookOutput = {
  hookSpecificOutput?: { hookEventName: string; additionalContext: string };
};

describe("createMemoryKillNoticeHook", () => {
  let dir: string;
  let path: string;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "memory-kill-hook-"));
    path = join(dir, "events.jsonl");
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it.each([
    ["PostToolUse", "Bash"],
    ["PostToolUseFailure", "Bash"],
    ["PostToolUse", "BashOutput"],
  ] as const)(
    "tells the agent about a new kill once after a %s %s call",
    async (hookEventName, toolName) => {
      await writeFile(
        path,
        `${killRecord(7, STARTED_AT_SECONDS - 60)}\n${killRecord(8, STARTED_AT_SECONDS + 5)}\n`,
      );
      const hook = createMemoryKillNoticeHook(new Logger({ debug: false }), {
        reader: new MemoryWatchdogKillReader(path),
        startedAtMs: STARTED_AT_SECONDS * 1000,
        killRecordWaitMs: 0,
      });
      const opts = { signal: new AbortController().signal };

      const first = (await hook(
        shellInput(hookEventName, toolName),
        "toolu_1",
        opts,
      )) as HookOutput;
      const second = await hook(
        shellInput(hookEventName, toolName),
        "toolu_2",
        opts,
      );

      expect(first.hookSpecificOutput?.hookEventName).toBe(hookEventName);
      const context = first.hookSpecificOutput?.additionalContext ?? "";
      expect(context).toContain("(pid 8) with SIGKILL");
      expect(context).toContain("22.0 GiB");
      expect(context).not.toContain("pid 7");
      expect(second).toEqual({ continue: true });
    },
  );

  it.each([137, 143, 144])(
    "waits for a kill record written after Bash exits with code %s",
    async (exitCode) => {
      await writeFile(path, "");
      const reader = new MemoryWatchdogKillReader(path);
      const read = reader.readNewKills.bind(reader);
      let reads = 0;
      reader.readNewKills = async () => {
        const kills = await read();
        reads += 1;
        if (reads === 1) {
          await appendFile(path, `${killRecord(8, STARTED_AT_SECONDS + 5)}\n`);
        }
        return kills;
      };
      const hook = createMemoryKillNoticeHook(new Logger({ debug: false }), {
        reader,
        startedAtMs: STARTED_AT_SECONDS * 1000,
        killRecordWaitMs: 60_000,
        killRecordPollMs: 1,
      });

      const result = (await hook(
        shellInput("PostToolUseFailure", "Bash", `Exit code ${exitCode}`),
        "toolu_1",
        { signal: new AbortController().signal },
      )) as HookOutput;

      expect(result.hookSpecificOutput?.additionalContext).toContain("(pid 8)");
    },
  );

  it("retains a kill for each worker and the parent after another shell reads it", async () => {
    await writeFile(path, `${killRecord(8, STARTED_AT_SECONDS + 5)}\n`);
    const hook = createMemoryKillNoticeHook(new Logger({ debug: false }), {
      reader: new MemoryWatchdogKillReader(path),
      startedAtMs: STARTED_AT_SECONDS * 1000,
      killRecordWaitMs: 0,
    });
    const opts = { signal: new AbortController().signal };
    for (const agentId of ["worker-a", "worker-b", undefined]) {
      const input = {
        ...shellInput("PostToolUse", agentId ? "Bash" : "Agent"),
        agent_id: agentId,
      };
      const output = (await hook(input, "toolu_1", opts)) as HookOutput;
      expect(output.hookSpecificOutput?.additionalContext).toContain("(pid 8)");
      expect(await hook(input, "toolu_2", opts)).toEqual({ continue: true });
    }
  });

  it.each([
    ["pnpm test", "pnpm test tests/small.test.ts"],
    [
      "cd /tmp/project && pnpm test",
      "cd /tmp/project && pnpm test tests/small.test.ts",
    ],
    ["timeout 1m pnpm test", "timeout 1m pnpm test tests/small.test.ts"],
    ["npx tsgo --noEmit", "npx tsgo --noEmit -p tsconfig.small.json"],
    ["hogli test tests", "hogli test tests/unit"],
    ['out="$(pnpm test)"', 'out="$(pnpm test tests/small.test.ts)"'],
    [
      "timeout 1m \\\n pnpm backend:test",
      "timeout 1m \\\n pnpm backend:test tests/unit",
    ],
    [
      "cat <<'EOF'\nliteral\nEOF\npnpm test",
      "cat <<'EOF'\nliteral\nEOF\npnpm test tests/unit",
    ],
    [
      'flox activate -- bash -c "pnpm test"',
      'flox activate -- bash -c "pnpm test tests/small.test.ts"',
    ],
  ])(
    "serializes %s and scopes retry limits to its directory",
    async (command, smallerCommand) => {
      await writeFile(path, "");
      const hook = createMemoryKillNoticeHook(new Logger({ debug: false }), {
        reader: new MemoryWatchdogKillReader(path),
        startedAtMs: STARTED_AT_SECONDS * 1000,
        killRecordWaitMs: 0,
      });
      const opts = { signal: new AbortController().signal };
      const pre = {
        ...shellInput("PostToolUse"),
        hook_event_name: "PreToolUse" as const,
        tool_input: { command },
      };
      expect(await hook(pre, "toolu_1", opts)).toMatchObject({
        hookSpecificOutput: {
          updatedInput: { command: `${VALIDATION_LOCK_PREFIX}${command}` },
        },
      });
      for (const pid of [8, 9]) {
        await appendFile(
          path,
          `${killRecord(pid, STARTED_AT_SECONDS + pid)}\n`,
        );
        const failure = {
          ...shellInput("PostToolUseFailure", "Bash", "Exit code 144"),
          tool_input: { command: `${VALIDATION_LOCK_PREFIX}${command}` },
        };
        await hook(failure, `toolu_${pid}`, opts);
        if (pid === 8) {
          await hook(
            {
              ...failure,
              agent_id: "another-worker",
            },
            "toolu_worker",
            opts,
          );
          expect(await hook(pre, "toolu_retry", opts)).toMatchObject({
            hookSpecificOutput: {
              updatedInput: { command: `${VALIDATION_LOCK_PREFIX}${command}` },
            },
          });
        }
      }
      expect(await hook(pre, "toolu_3", opts)).toMatchObject({
        hookSpecificOutput: { permissionDecision: "deny" },
      });
      expect(
        await hook(
          { ...pre, tool_input: { command: smallerCommand } },
          "toolu_4",
          opts,
        ),
      ).toMatchObject({
        hookSpecificOutput: {
          updatedInput: {
            command: `${VALIDATION_LOCK_PREFIX}${smallerCommand}`,
          },
        },
      });
      for (const otherDirectory of [
        { ...pre, cwd: "/tmp/other-worktree" },
        {
          ...pre,
          tool_input: { command: "cd /tmp/other-project && pnpm test" },
        },
      ]) {
        expect(await hook(otherDirectory, "toolu_other", opts)).toMatchObject({
          hookSpecificOutput: {
            updatedInput: {
              command: `${VALIDATION_LOCK_PREFIX}${otherDirectory.tool_input.command}`,
            },
          },
        });
      }
    },
  );
});
