import { appendFile, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { HookInput } from "@anthropic-ai/claude-agent-sdk";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { MemoryWatchdogKillReader } from "../../../server/memory-watchdog";
import { Logger } from "../../../utils/logger";
import { createMemoryKillNoticeHook } from "./memory-kill-hook";

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
): HookInput {
  return {
    session_id: "s",
    transcript_path: "/tmp/t",
    cwd: "/tmp",
    hook_event_name: hookEventName,
    tool_name: toolName,
    tool_input: { command: "pnpm test" },
    tool_use_id: "toolu_1",
    ...(hookEventName === "PostToolUse" ? { tool_response: "" } : { error }),
  } as unknown as HookInput;
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

  it("waits for a kill record written after Bash exits with a signal code", async () => {
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
      shellInput("PostToolUseFailure", "Bash", "Exit code 143"),
      "toolu_1",
      { signal: new AbortController().signal },
    )) as HookOutput;

    expect(result.hookSpecificOutput?.additionalContext).toContain("(pid 8)");
  });
});
