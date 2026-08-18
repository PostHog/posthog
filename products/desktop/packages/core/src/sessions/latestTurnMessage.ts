import type { AcpMessage, JsonRpcMessage } from "@posthog/shared";
import { isJsonRpcNotification } from "@posthog/shared";

/**
 * The last thing the agent actually said, for surfaces that show a task without
 * opening it.
 *
 * Two sources, because neither covers every task on its own: a session loaded
 * in this window has the live events, and a cloud run persists the text of each
 * finished turn on the run itself. A task you have never opened only has the
 * second; a turn streaming right now only has the first.
 */

/** The key the cloud relay writes each finished turn's closing prose under. */
const FINAL_MESSAGE_KEY = "final_message";

/**
 * How far back a scan walks before giving up. A long session holds tens of
 * thousands of events and this runs while a card is open on a streaming turn,
 * so the scan is bounded rather than proportional to the transcript. An agent
 * message that is further back than this is old enough that the run's persisted
 * text is the better answer anyway.
 */
const MAX_SCANNED_EVENTS = 500;

/** Longer than this and the card is a transcript. Cut on a word boundary. */
const MAX_MESSAGE_CHARS = 240;

/**
 * The text of a `session/update` carrying agent prose, or null for anything
 * else — a thought, a tool call, a user chunk, a response.
 */
function agentMessageText(message: JsonRpcMessage): string | null {
  if (!isJsonRpcNotification(message) || message.method !== "session/update") {
    return null;
  }
  const update = (message.params as { update?: unknown } | undefined)?.update as
    | {
        sessionUpdate?: string;
        content?: { type?: string; text?: string };
      }
    | undefined;
  if (update?.sessionUpdate !== "agent_message_chunk") return null;
  if (update.content?.type !== "text") return null;
  return update.content.text ?? null;
}

/**
 * The agent's most recent message, assembled from the streamed chunks it came
 * in as.
 *
 * Chunks of one message arrive consecutively, so the message is the run of
 * chunks ending at the last one: walking back from there stops at the first
 * event that isn't prose (a tool call, a thought, the user's turn), which is
 * where that message began.
 */
export function latestAgentMessage(
  events: readonly AcpMessage[] | undefined,
): string | null {
  if (!events?.length) return null;
  const floor = Math.max(0, events.length - MAX_SCANNED_EVENTS);
  let end = -1;
  for (let i = events.length - 1; i >= floor; i--) {
    if (agentMessageText(events[i].message) != null) {
      end = i;
      break;
    }
  }
  if (end === -1) return null;

  const chunks: string[] = [];
  for (let i = end; i >= floor; i--) {
    const text = agentMessageText(events[i].message);
    if (text == null) break;
    chunks.unshift(text);
  }
  return condenseTurnMessage(chunks.join(""));
}

/**
 * The closing message of the last turn a cloud run finished, which the relay
 * persists on the run as it ends.
 */
export function persistedTurnMessage(
  output: Record<string, unknown> | null | undefined,
): string | null {
  const message = output?.[FINAL_MESSAGE_KEY];
  return typeof message === "string" ? condenseTurnMessage(message) : null;
}

/**
 * One line of prose out of a message that may be many. Markdown is left as
 * typed — stripping it half-way reads worse than the source does, and the
 * surfaces that show this clamp to a couple of lines anyway.
 */
export function condenseTurnMessage(text: string): string | null {
  const collapsed = text.replace(/\s+/g, " ").trim();
  if (!collapsed) return null;
  if (collapsed.length <= MAX_MESSAGE_CHARS) return collapsed;
  const cut = collapsed.slice(0, MAX_MESSAGE_CHARS);
  const lastSpace = cut.lastIndexOf(" ");
  return `${(lastSpace > MAX_MESSAGE_CHARS / 2 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
}
