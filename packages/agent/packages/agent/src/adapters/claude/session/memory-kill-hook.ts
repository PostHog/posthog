import { setTimeout as sleep } from "node:timers/promises";
import type { HookCallback, HookInput } from "@anthropic-ai/claude-agent-sdk";
import type { ProcessKilledParams } from "../../../acp-extensions";
import { MemoryWatchdogKillReader } from "../../../server/memory-watchdog";
import type { Logger } from "../../../utils/logger";

const BYTES_PER_GIB = 1024 ** 3;
// BashOutput and TaskOutput return the result of a background Bash command,
// which the watchdog can stop after the Bash call itself has returned.
const SHELL_RESULT_TOOLS = new Set(["Bash", "BashOutput", "TaskOutput"]);
const SIGNAL_EXIT_PATTERN = /exit[ _]?code"?\s*:?\s*(137|143)\b/i;
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
    "The exit status of that command is from this stop, not from the command itself.",
    "If you run the same command again without changes, the sandbox will stop it again.",
    "Run a smaller command instead: fewer test files, fewer parallel workers, or one package at a time.",
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
  const readKills = async (): Promise<ProcessKilledParams[]> =>
    (await reader.readNewKills()).filter(
      (kill) => Date.parse(kill.at) >= startedAtMs,
    );

  return async (input: HookInput, _toolUseId, { signal }) => {
    if (
      input.hook_event_name !== "PostToolUse" &&
      input.hook_event_name !== "PostToolUseFailure"
    ) {
      return { continue: true };
    }
    if (!SHELL_RESULT_TOOLS.has(input.tool_name)) return { continue: true };

    let kills: ProcessKilledParams[];
    try {
      kills = await readKills();
      if (kills.length === 0 && endedBySignal(input)) {
        const deadline = Date.now() + killRecordWaitMs;
        while (kills.length === 0 && Date.now() < deadline && !signal.aborted) {
          await sleep(killRecordPollMs);
          kills = await readKills();
        }
      }
    } catch (error) {
      logger.debug("Memory watchdog events read failed", {
        error: error instanceof Error ? error.message : String(error),
      });
      return { continue: true };
    }
    if (kills.length === 0) return { continue: true };

    return {
      continue: true,
      hookSpecificOutput: {
        hookEventName: input.hook_event_name,
        additionalContext: formatMemoryKillNotice(kills),
      },
    };
  };
};
