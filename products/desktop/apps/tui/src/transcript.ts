import { convertStoredEntriesToEvents } from "@posthog/core/sessions/sessionEvents";
import {
  type AgentConversationEvent,
  type AgentRuntime,
  type StoredLogEntry,
  showActionSchema,
} from "@posthog/shared";
import {
  buildAgentConversationItems,
  buildConversationItems,
  type ConversationItem,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import { z } from "zod";

export type TranscriptLine =
  | { kind: "user"; id: string; text: string }
  | { kind: "assistant"; id: string; text: string }
  | ToolLine
  | { kind: "notice"; id: string; text: string; tone: "info" | "error" }
  | { kind: "actions"; id: string; actions: ShowAction[] }
  | ShellLine;

// A shell command the user ran with ! in the composer, not one the agent ran.
export interface ShellLine {
  kind: "shell";
  id: string;
  command: string;
  status: string;
  output: string;
}

// A command shown before the run's log has it; seen counts the logged runs of the same command when it started.
export interface PendingShell {
  line: ShellLine;
  seen: number;
}

export interface ToolLine {
  kind: "tool";
  id: string;
  title: string;
  status: string;
  // What the call worked on, such as a shell command or a file path.
  detail: string;
  output: string;
}

export interface Transcript {
  lines: TranscriptLine[];
  // The agent is mid-turn: a prompt it has not finished answering.
  turnOpen: boolean;
  // The latest turn once it has finished: how long it took and when it ended (epoch ms).
  lastTurn: { durationMs: number; endedAt: number } | null;
  // When the open turn started (epoch ms), or null between turns.
  turnStartedAt: number | null;
}

// Pi runs log conversation events; ACP runs (Claude, Codex) log raw ACP notifications.
export function transcriptFrom(
  runtime: AgentRuntime | undefined,
  entries: StoredLogEntry[],
  taskDescription?: string,
): Transcript {
  const built =
    runtime === "pi"
      ? buildAgentConversationItems(
          entries.flatMap((entry): AgentConversationEvent[] =>
            entry.type === "pi_event" && entry.event ? [entry.event] : [],
          ),
          null,
        )
      : buildConversationItems(
          convertStoredEntriesToEvents(entries, taskDescription),
          null,
        );
  const lines = built.items.flatMap(toLine);
  const turnOpen = built.lastTurnInfo?.isComplete === false;
  // An open turn holds its negated start time until it completes.
  const turnStartedAt =
    turnOpen && built.lastTurnInfo ? -built.lastTurnInfo.durationMs : null;
  const lastTurn =
    built.lastTurnInfo?.isComplete && built.lastActivityAt !== null
      ? {
          durationMs: built.lastTurnInfo.durationMs,
          endedAt: built.lastActivityAt,
        }
      : null;
  // The sandbox echoes a new chat's first message only once it boots, so show it until then.
  if (
    runtime === "pi" &&
    taskDescription &&
    !lines.some((line) => line.kind === "user")
  ) {
    return {
      lines: [
        { kind: "user", id: "first-message", text: taskDescription },
        ...lines,
      ],
      turnOpen,
      lastTurn,
      turnStartedAt,
    };
  }
  return { lines, turnOpen, lastTurn, turnStartedAt };
}

// Bookkeeping the harness asks for every turn; it says nothing about the work.
const SUMMARY_TOOL = "task_summary_update";
// Buttons the agent offers; the desktop app draws them, and here the action picker does.
const ACTIONS_TOOL = "show_actions";
const actionsInput = z.object({ actions: z.array(showActionSchema).min(1) });
export type ShowAction = z.infer<typeof showActionSchema>;

function toLine(item: ConversationItem): TranscriptLine[] {
  if (item.type === "user_message") {
    return [{ kind: "user", id: item.id, text: item.content }];
  }
  if (item.type === "turn_cancelled") {
    return [{ kind: "notice", id: item.id, text: "Cancelled", tone: "info" }];
  }
  if (item.type !== "session_update") return [];
  const update = item.update;
  switch (update.sessionUpdate) {
    case "agent_message_chunk":
      return update.content.type === "text"
        ? [{ kind: "assistant", id: item.id, text: update.content.text }]
        : [];
    case "tool_call":
      if (update.title.endsWith(SUMMARY_TOOL)) return [];
      if ("origin" in update && update.origin === "user_shell") {
        return [
          {
            kind: "shell",
            id: item.id,
            command: update.title,
            status: update.status ?? "pending",
            output: toolOutput(update.content, update.rawOutput),
          },
        ];
      }
      if (update.title.endsWith(ACTIONS_TOOL)) {
        const input = actionsInput.safeParse(update.rawInput);
        return update.status !== "failed" && input.success
          ? [{ kind: "actions", id: item.id, actions: input.data.actions }]
          : [];
      }
      return [
        {
          kind: "tool",
          id: item.id,
          title: update.title,
          status: update.status ?? "pending",
          detail: toolDetail(update.rawInput),
          output: toolOutput(update.content, update.rawOutput),
        },
      ];
    case "status":
      return update.error
        ? [{ kind: "notice", id: item.id, text: update.error, tone: "error" }]
        : [];
    default:
      return [];
  }
}

function toolDetail(input: unknown): string {
  if (!input || typeof input !== "object") return "";
  const fields = input as Record<string, unknown>;
  const main = fields.command ?? fields.path ?? fields.file_path;
  return typeof main === "string" ? main : JSON.stringify(input);
}

const textOf = (blocks: unknown): string[] =>
  Array.isArray(blocks)
    ? blocks.flatMap((block) => {
        const inner = block?.type === "content" ? block.content : block;
        return inner?.type === "text" ? [inner.text as string] : [];
      })
    : [];

function toolOutput(content: unknown, rawOutput: unknown): string {
  const text = [...textOf(content), ...textOf(rawOutput)].join("\n");
  return text || (typeof rawOutput === "string" ? rawOutput : "");
}

const plural = (count: number, noun: string): string =>
  `${count} ${noun}${count === 1 ? "" : "s"}`;

// What each tool's calls count as, a verb and the noun it counts, and what a call in flight is doing.
function phraseOf(title: string): [string, string, string] {
  const name = title.toLowerCase();
  if (name === "bash") return ["ran", "shell command", "Running"];
  if (name === "read") return ["read", "file", "Reading"];
  if (name === "edit" || name === "write") return ["edited", "file", "Editing"];
  if (name === "grep" || name === "find" || name === "ls")
    return ["searched", "time", "Searching"];
  const label = name.includes("posthog") ? "PostHog" : name;
  return [`called ${label}`, "time", `Calling ${label}`];
}

export const activityOf = (title: string): string => phraseOf(title)[2];

// How a run of tool calls reads collapsed, like "Ran 5 shell commands · read 2 files".
export function toolSummary(tools: ToolLine[]): string {
  const counts = new Map<string, { noun: string; count: number }>();
  for (const tool of tools) {
    const [verb, noun] = phraseOf(tool.title);
    const entry = counts.get(verb) ?? { noun, count: 0 };
    counts.set(verb, { ...entry, count: entry.count + 1 });
  }
  const text = [...counts]
    .map(([verb, { noun, count }]) => `${verb} ${plural(count, noun)}`)
    .join(" · ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// A message the user just sent shows at once, until the run's log echoes it back as its latest user message.
export function withPending(
  lines: TranscriptLine[],
  pending: string | null,
): TranscriptLine[] {
  if (!pending) return lines;
  const lastUser = lines.findLast((line) => line.kind === "user");
  if (lastUser?.kind === "user" && lastUser.text === pending) return lines;
  return [...lines, { kind: "user", id: "pending", text: pending }];
}

// How many runs of a command the transcript already shows.
export function shellRuns(lines: TranscriptLine[], command: string): number {
  return lines.filter(
    (line) => line.kind === "shell" && line.command === command,
  ).length;
}

// Commands the user just ran show at once, each until the run's log has a run of it beyond the ones it saw.
export function withPendingShells(
  lines: TranscriptLine[],
  pending: PendingShell[],
): TranscriptLine[] {
  const waiting = pending.filter(
    ({ line, seen }) => shellRuns(lines, line.command) <= seen,
  );
  return [...lines, ...waiting.map(({ line }) => line)];
}
