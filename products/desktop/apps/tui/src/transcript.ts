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
import { tokenCount } from "./usage";

export type TranscriptLine =
  | UserLine
  | { kind: "assistant"; id: string; text: string }
  | ToolLine
  | { kind: "notice"; id: string; text: string; tone: "info" | "error" }
  // The sheet is titled "Suggested actions" unless the offer names its own title.
  | { kind: "actions"; id: string; actions: ShowAction[]; title?: string }
  | ShellLine;

// A message the user sent, with the images that went with it.
export interface UserLine {
  kind: "user";
  id: string;
  text: string;
  images?: SentImage[];
}

export interface SentImage {
  data: string;
  mimeType: string;
}

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
  // The latest turn once it has finished: how long it took, when it ended (epoch ms) and why it stopped.
  lastTurn: { durationMs: number; endedAt: number; stopReason?: string } | null;
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
          withCompactions(
            entries.flatMap((entry): AgentConversationEvent[] =>
              entry.type === "pi_event" && entry.event ? [entry.event] : [],
            ),
          ),
          null,
        )
      : buildConversationItems(
          convertStoredEntriesToEvents(entries, taskDescription),
          null,
        );
  const lines =
    runtime === "pi"
      ? withImages(built.items.flatMap(toLine), entries)
      : built.items.flatMap(toLine);
  const turnOpen = built.lastTurnInfo?.isComplete === false;
  // An open turn holds its negated start time until it completes.
  const turnStartedAt =
    turnOpen && built.lastTurnInfo ? -built.lastTurnInfo.durationMs : null;
  const lastTurn =
    built.lastTurnInfo?.isComplete && built.lastActivityAt !== null
      ? {
          durationMs: built.lastTurnInfo.durationMs,
          endedAt: built.lastActivityAt,
          stopReason: built.lastTurnInfo.stopReason,
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

// The conversation builder keeps a message's text and drops its images, so each user line takes them back
// from the first unclaimed pi message with the same text.
function withImages(
  lines: TranscriptLine[],
  entries: StoredLogEntry[],
): TranscriptLine[] {
  const sent = entries.flatMap((entry) => {
    const event = entry.type === "pi_event" ? entry.event : undefined;
    if (event?.type !== "user_message") return [];
    const images = event.content.flatMap((block) =>
      block.type === "image"
        ? [{ data: block.data, mimeType: block.mimeType }]
        : [],
    );
    if (images.length === 0) return [];
    const text = event.content
      .flatMap((block) => (block.type === "text" ? [block.text] : []))
      .join("")
      .trim();
    return [{ text, images }];
  });
  if (sent.length === 0) return lines;
  return lines.map((line) => {
    if (line.kind !== "user") return line;
    const index = sent.findIndex(({ text }) => text === line.text.trim());
    if (index < 0) return line;
    const [{ images }] = sent.splice(index, 1);
    return { ...line, images };
  });
}

// Statuses that stand in for a compaction: the /compact that started it, and what it freed.
const COMPACT_REQUESTED = "tui_compact_requested";
const COMPACTED = "tui_compacted";

type Compaction = Extract<
  AgentConversationEvent,
  { type: "runtime_status" }
>["compaction"];

// A compaction's summary is for the model, so the chat shows a line about it in its place.
// The summary arrives as an agent message with the same time as the compaction's end.
function withCompactions(
  events: AgentConversationEvent[],
): AgentConversationEvent[] {
  return events.flatMap((event, index) => {
    const previous = events[index - 1];
    const ended = (status: AgentConversationEvent | undefined): boolean =>
      status?.type === "runtime_status" &&
      status.status === "compacting" &&
      status.isComplete === true;
    if (
      event.type === "assistant_message_chunk" &&
      ended(previous) &&
      previous.timestamp === event.timestamp
    )
      return [];
    if (event.type !== "runtime_status" || event.status !== "compacting")
      return [event];
    if (!event.isComplete) {
      return event.compaction?.reason === "manual"
        ? [
            event,
            {
              ...event,
              status: COMPACT_REQUESTED,
              message: ["/compact", event.compaction.instructions]
                .filter(Boolean)
                .join(" "),
            },
          ]
        : [event];
    }
    // A stopped compaction ends without a summary, and freed nothing.
    const summary = events[index + 1];
    const compacted =
      summary?.type === "assistant_message_chunk" &&
      summary.timestamp === event.timestamp;
    return compacted
      ? [
          event,
          {
            ...event,
            status: COMPACTED,
            isComplete: undefined,
            message: compactedText(event.compaction),
          },
        ]
      : [event];
  });
}

function compactedText(compaction: Compaction): string {
  const automatic = compaction && compaction.reason !== "manual";
  const before = compaction?.tokensBefore;
  if (before === undefined)
    return automatic ? "Compacted automatically" : "Compacted";
  const after = compaction?.estimatedTokensAfter;
  const sizes = `${tokenCount(before)}${after === undefined ? "" : ` → ~${tokenCount(after)}`} tokens`;
  return automatic ? `Compacted automatically: ${sizes}` : `Compacted ${sizes}`;
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
      if (update.status === COMPACT_REQUESTED && update.message)
        return [{ kind: "user", id: item.id, text: update.message }];
      if (update.status === COMPACTED && update.message)
        return [
          { kind: "notice", id: item.id, text: update.message, tone: "info" },
        ];
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
export const PENDING_ID = "pending";
export function withPending(
  lines: TranscriptLine[],
  pending: string | null,
): TranscriptLine[] {
  if (!pending) return lines;
  const lastUser = lines.findLast((line) => line.kind === "user");
  if (lastUser?.kind === "user" && lastUser.text === pending) return lines;
  return [...lines, { kind: "user", id: PENDING_ID, text: pending }];
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
