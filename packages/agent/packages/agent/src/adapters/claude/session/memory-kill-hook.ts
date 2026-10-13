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
const SIGNAL_EXIT_PATTERN =
  /(?:exit[ _]?code"?\s*:?\s*|exited with code\s+)(137|143|144)\b/i;
// The watchdog writes the kill record only after the process tree is gone
// and memory is below the trigger. That takes up to two grace periods of
// 2 seconds each, so the record can arrive after the shell has exited.
const KILL_RECORD_WAIT_MS = 5_000;
const KILL_RECORD_POLL_MS = 250;
// A kill belongs to a command when the record's timestamp falls between the
// command's start and the record delay after its end. The lead covers clock
// jitter when a command's start is only known from its result.
const KILL_RECORD_DELAY_MS = 6_000;
const KILL_RECORD_LEAD_MS = 1_000;
// A command that ran shorter than this cannot have been the memory-heavy one,
// so a fast rerun of it does not wait for a trailing kill record.
const MIN_STOPPABLE_RUN_MS = 2_000;
const RUN_RETENTION_MS = 60_000;
const MAX_RUNS = 200;
const MAX_KILLS = 100;

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
    "Do not rerun a stopped command unchanged.",
    "Run a smaller command instead: fewer test files, fewer parallel workers, or one package at a time.",
    "Coordinate with the parent and other agents: run only one memory-heavy build, test suite, or typecheck at a time across all worktrees. Do not start another copy in the background.",
  ].join("\n");
}

export interface MemoryKillNoticeHookOptions {
  reader?: MemoryWatchdogKillReader;
  startedAtMs?: number;
  killRecordWaitMs?: number;
  killRecordPollMs?: number;
  // Codex hook payloads carry the command output without its exit status, so
  // a stopped command is recognized only by a kill record near its end.
  exitStatusInToolResponse?: boolean;
  now?: () => number;
}

interface CommandRun {
  retryKey: string;
  startedAtMs: number;
  endedAtMs?: number;
  // Undefined when the payload cannot show the exit status.
  endedBySignal?: boolean;
  stopped: boolean;
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

function killId(kill: ProcessKilledParams): string {
  return `${kill.at}:${kill.pid}`;
}

function denyReason(validation: string | undefined): string {
  const scope = validation
    ? "This validation command has failed repeatedly during watchdog memory interventions. Do not retry it unchanged. Reduce its scope or worker count, or report that validation could not complete within the sandbox memory limit."
    : "The sandbox memory watchdog stopped this command twice. Do not retry it unchanged. Reduce its memory use, scope, or worker count, or report that it could not complete within the sandbox memory limit.";
  return `${scope} To run it in a different directory, start the command with \`cd <directory> &&\`.`;
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
    exitStatusInToolResponse = true,
    now = Date.now,
  }: MemoryKillNoticeHookOptions = {},
): HookCallback => {
  const killsById = new Map<string, ProcessKilledParams>();
  const delivered = new Map<string, Set<string>>();
  const runs = new Map<string, CommandRun>();
  const failures = new Map<string, { count: number; killIds: Set<string> }>();

  const readKills = async (): Promise<ProcessKilledParams[]> =>
    (await reader.readNewKills()).filter(
      (kill) => Date.parse(kill.at) >= startedAtMs,
    );

  const stoppedBy = (run: CommandRun, kill: ProcessKilledParams): boolean => {
    if (run.endedAtMs === undefined || run.endedBySignal === false)
      return false;
    const killAtMs = Date.parse(kill.at);
    return (
      killAtMs >= run.startedAtMs - KILL_RECORD_LEAD_MS &&
      killAtMs <= run.endedAtMs + KILL_RECORD_DELAY_MS
    );
  };

  // Retry counting must not depend on which agent read a kill first: with
  // parallel tool calls, an unrelated result can read the record before the
  // stopped command's own result arrives.
  const attributeKills = (): void => {
    for (const run of runs.values()) {
      if (run.stopped) continue;
      const ids = [...killsById.values()]
        .filter((kill) => stoppedBy(run, kill))
        .map(killId);
      if (ids.length === 0) continue;
      run.stopped = true;
      const interventions = failures.get(run.retryKey) ?? {
        count: 0,
        killIds: new Set<string>(),
      };
      // One intervention counts once, however many runs of the key it ended.
      if (ids.some((id) => !interventions.killIds.has(id))) {
        interventions.count += 1;
      }
      for (const id of ids) interventions.killIds.add(id);
      failures.set(run.retryKey, interventions);
    }
  };

  const pruneRuns = (): void => {
    const cutoff = now() - RUN_RETENTION_MS;
    for (const [id, run] of runs) {
      if (run.endedAtMs !== undefined && run.endedAtMs < cutoff)
        runs.delete(id);
    }
    while (runs.size > MAX_RUNS) {
      const oldest = runs.keys().next().value;
      if (oldest === undefined) break;
      runs.delete(oldest);
    }
  };

  const refreshKills = async (): Promise<void> => {
    for (const kill of await readKills()) killsById.set(killId(kill), kill);
    while (killsById.size > MAX_KILLS) {
      const oldest = killsById.keys().next().value;
      if (oldest === undefined) break;
      killsById.delete(oldest);
      for (const consumerSeen of delivered.values())
        consumerSeen.delete(oldest);
    }
    pruneRuns();
    attributeKills();
  };

  const pollUntil = async (
    done: () => boolean,
    deadlineMs: number,
    signal: AbortSignal,
  ): Promise<void> => {
    while (!done() && now() < deadlineMs && !signal.aborted) {
      await sleep(killRecordPollMs);
      await refreshKills();
    }
  };

  const latestRun = (retryKey: string): CommandRun | undefined => {
    let latest: CommandRun | undefined;
    for (const run of runs.values()) {
      if (run.retryKey !== retryKey || run.endedAtMs === undefined) continue;
      if (latest?.endedAtMs === undefined || run.endedAtMs > latest.endedAtMs)
        latest = run;
    }
    return latest;
  };

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
    const retryKey =
      input.tool_name === "Bash" && command
        ? JSON.stringify([input.cwd, validation || command.trim()])
        : undefined;
    const runId = input.tool_use_id || toolUseId;

    const consumer = input.agent_id ?? input.session_id;
    const seen = delivered.get(consumer) ?? new Set<string>();
    delivered.set(consumer, seen);
    // Every worker needs the warning; a fast unrelated shell must not consume it.
    const takeUnseenKills = (): ProcessKilledParams[] => {
      const kills = [...killsById.values()].filter(
        (kill) => !seen.has(killId(kill)),
      );
      for (const kill of kills) seen.add(killId(kill));
      return kills;
    };

    if (input.hook_event_name === "PreToolUse") {
      if (!retryKey || !command) return { continue: true };
      try {
        await refreshKills();
        const previous = latestRun(retryKey);
        if (
          !exitStatusInToolResponse &&
          previous?.endedAtMs !== undefined &&
          !previous.stopped &&
          previous.endedAtMs - previous.startedAtMs >= MIN_STOPPABLE_RUN_MS
        ) {
          await pollUntil(
            () => previous.stopped,
            previous.endedAtMs + killRecordWaitMs,
            signal,
          );
        }
      } catch (error) {
        logger.debug("Memory watchdog events read failed", {
          error: error instanceof Error ? error.message : String(error),
        });
        return { continue: true };
      }
      if ((failures.get(retryKey)?.count ?? 0) >= 2) {
        return {
          continue: true,
          hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: denyReason(validation || undefined),
          },
        };
      }
      if (runId) {
        runs.set(runId, { retryKey, startedAtMs: now(), stopped: false });
      }
      const kills = takeUnseenKills();
      if (!validation && kills.length === 0) return { continue: true };
      return {
        continue: true,
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          ...(validation
            ? {
                updatedInput: {
                  ...toolInput,
                  command: serializeValidation(command),
                },
              }
            : {}),
          ...(kills.length > 0
            ? { additionalContext: formatMemoryKillNotice(kills) }
            : {}),
        },
      };
    }

    let run: CommandRun | undefined;
    if (retryKey && runId) {
      run = runs.get(runId) ?? { retryKey, startedAtMs: now(), stopped: false };
      run.endedAtMs = now();
      run.endedBySignal = exitStatusInToolResponse
        ? endedBySignal(input)
        : undefined;
      runs.set(runId, run);
    }

    const hasUnseenKills = (): boolean =>
      [...killsById.keys()].some((id) => !seen.has(id));
    let kills: ProcessKilledParams[];
    try {
      await refreshKills();
      const waitForRecord = run
        ? run.endedBySignal === true && !run.stopped
        : endedBySignal(input) && !hasUnseenKills();
      if (waitForRecord) {
        await pollUntil(
          () => (run ? run.stopped : hasUnseenKills()),
          now() + killRecordWaitMs,
          signal,
        );
      }
      kills = takeUnseenKills();
    } catch (error) {
      logger.debug("Memory watchdog events read failed", {
        error: error instanceof Error ? error.message : String(error),
      });
      return { continue: true };
    }
    if (kills.length === 0) return { continue: true };

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
