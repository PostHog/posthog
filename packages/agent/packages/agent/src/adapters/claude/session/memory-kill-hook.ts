import { setTimeout as sleep } from "node:timers/promises";
import type {
  HookCallback,
  HookInput,
  HookJSONOutput,
} from "@anthropic-ai/claude-agent-sdk";
import type { ProcessKilledParams } from "../../../acp-extensions";
import { MemoryWatchdogKillReader } from "../../../server/memory-watchdog";
import type { Logger } from "../../../utils/logger";
import { serializeValidation, validationCommandKey } from "./memory-validation";

const BYTES_PER_GIB = 1024 ** 3;
// BashOutput and TaskOutput return the result of a background Bash command,
// which the watchdog can stop after the Bash call itself has returned.
const SHELL_RESULT_TOOLS = new Set(["Bash", "BashOutput", "TaskOutput"]);
const SIGNAL_EXIT_PATTERN = /exit[ _]?code"?\s*:?\s*(137|143|144)\b/i;
// The watchdog writes the kill record only after the process tree is gone
// and memory is below the trigger. That takes up to two grace periods of
// 2 seconds each, so the record can arrive after the shell has exited.
const KILL_RECORD_WAIT_MS = 5_000;
const KILL_RECORD_POLL_MS = 250;

function formatGib(bytes: number): string {
  return `${(bytes / BYTES_PER_GIB).toFixed(1)} GiB`;
}

export function formatMemoryKillNotice(kills: ProcessKilledParams[]): string {
  const lines = kills.map(
    (kill) =>
      `- ${kill.at}: stopped \`${kill.comm}\` (pid ${kill.pid}) with ${kill.signal}. Its process tree used ${formatGib(kill.treeRssBytes)}. Sandbox memory was at ${formatGib(kill.memoryCurrentBytes)} of ${formatGib(kill.memoryLimitBytes)}.`,
  );
  return [
    "## Sandbox memory watchdog",
    "",
    "The sandbox stopped a shell command because the sandbox was close to its memory limit:",
    ...lines,
    "",
    "This notice describes memory pressure shared by every agent in the sandbox; it does not identify which tool call was stopped.",
    "Do not rerun a stopped validation command unchanged.",
    "Run a smaller command instead: fewer test files, fewer parallel workers, or one package at a time.",
    "Coordinate with the parent and other agents: run only one memory-heavy build, test suite, or typecheck at a time across all worktrees. Do not start another copy in the background.",
  ].join("\n");
}

export interface MemoryKillNoticeHookOptions {
  reader?: MemoryWatchdogKillReader;
  startedAtMs?: number;
  killRecordWaitMs?: number;
  killRecordPollMs?: number;
}

function endedBySignal(input: HookInput): boolean {
  const result =
    input.hook_event_name === "PostToolUseFailure"
      ? input.error
      : input.hook_event_name === "PostToolUse"
        ? input.tool_response
        : undefined;
  const text = typeof result === "string" ? result : JSON.stringify(result);
  return SIGNAL_EXIT_PATTERN.test(text ?? "");
}

// The Bash tool only sees an exit code when the watchdog stops its process
// tree, so without this notice the agent reruns the same command.
export const createMemoryKillNoticeHook = (
  logger: Logger,
  {
    reader = new MemoryWatchdogKillReader(),
    startedAtMs = Date.now(),
    killRecordWaitMs = KILL_RECORD_WAIT_MS,
    killRecordPollMs = KILL_RECORD_POLL_MS,
  }: MemoryKillNoticeHookOptions = {},
): HookCallback => {
  const killsById = new Map<string, ProcessKilledParams>();
  const delivered = new Map<string, Set<string>>();
  const stoppedCommands = new Map<
    string,
    { failures: number; killIds: Set<string> }
  >();
  const readKills = async (): Promise<ProcessKilledParams[]> =>
    (await reader.readNewKills()).filter(
      (kill) => Date.parse(kill.at) >= startedAtMs,
    );

  return async (
    input: HookInput,
    toolUseId,
    { signal },
  ): Promise<HookJSONOutput> => {
    if (
      input.hook_event_name !== "PreToolUse" &&
      input.hook_event_name !== "PostToolUse" &&
      input.hook_event_name !== "PostToolUseFailure"
    ) {
      return { continue: true };
    }
    if (
      !SHELL_RESULT_TOOLS.has(input.tool_name) &&
      input.tool_name !== "Agent"
    ) {
      return { continue: true };
    }

    const toolInput = input.tool_input as { command?: unknown } | undefined;
    const command =
      typeof toolInput?.command === "string" ? toolInput.command : undefined;
    const validation = command && validationCommandKey(command);
    const validationKey = validation && JSON.stringify([input.cwd, validation]);
    if (input.hook_event_name === "PreToolUse") {
      if (input.tool_name !== "Bash" || !validationKey || !command)
        return { continue: true };
      if ((stoppedCommands.get(validationKey)?.failures ?? 0) >= 2) {
        return {
          continue: true,
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason:
              "This validation command has failed repeatedly during watchdog memory interventions. Do not retry it unchanged. Reduce its scope or worker count, or report that validation could not complete within the sandbox memory limit.",
          },
        };
      }
      return {
        continue: true,
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          updatedInput: { ...toolInput, command: serializeValidation(command) },
        },
      };
    }

    const consumer = input.agent_id ?? input.session_id;
    const seen = delivered.get(consumer) ?? new Set<string>();
    delivered.set(consumer, seen);

    const pendingKills = async (): Promise<ProcessKilledParams[]> => {
      for (const kill of await readKills()) {
        killsById.set(`${kill.at}:${kill.pid}`, kill);
      }
      while (killsById.size > 100) {
        const oldest = killsById.keys().next().value;
        if (oldest === undefined) break;
        killsById.delete(oldest);
        for (const consumerSeen of delivered.values())
          consumerSeen.delete(oldest);
      }
      // Every worker needs the warning; a fast unrelated shell must not consume it.
      return [...killsById]
        .filter(([id]) => !seen.has(id))
        .map(([, kill]) => kill);
    };

    let kills: ProcessKilledParams[];
    try {
      kills = await pendingKills();
      if (kills.length === 0 && endedBySignal(input)) {
        const deadline = Date.now() + killRecordWaitMs;
        while (kills.length === 0 && Date.now() < deadline && !signal.aborted) {
          await sleep(killRecordPollMs);
          kills = await pendingKills();
        }
      }
    } catch (error) {
      logger.debug("Memory watchdog events read failed", {
        error: error instanceof Error ? error.message : String(error),
      });
      return { continue: true };
    }
    if (kills.length === 0) return { continue: true };

    for (const kill of kills) seen.add(`${kill.at}:${kill.pid}`);
    if (validationKey && endedBySignal(input)) {
      const interventions = stoppedCommands.get(validationKey) ?? {
        failures: 0,
        killIds: new Set<string>(),
      };
      const ids = kills.map((kill) => `${kill.at}:${kill.pid}`);
      if (ids.some((id) => !interventions.killIds.has(id))) {
        interventions.failures += 1;
        for (const id of ids) interventions.killIds.add(id);
      }
      stoppedCommands.set(validationKey, interventions);
    }
    logger.info("Memory watchdog feedback delivered to hook", {
      agentId: input.agent_id ?? null,
      toolUseId,
      killCount: kills.length,
    });

    return {
      continue: true,
      hookSpecificOutput: {
        hookEventName: input.hook_event_name,
        additionalContext: formatMemoryKillNotice(kills),
      },
    };
  };
};
