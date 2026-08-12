import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";

/**
 * A ticket points at its agent thread through a tag rather than a column,
 * because Conversations has no field for it yet. Keeping the encoding in one
 * place makes the swap to a real field a change to this file.
 *
 * The separator is a slash, not a hash: tags round-trip through systems that
 * strip hashes.
 */
const TASK_TAG_PREFIX = "ai-task:";

export function readTicketTaskId(
  tags: readonly string[] | undefined,
): string | null {
  for (const tag of tags ?? []) {
    if (tag.toLowerCase().startsWith(TASK_TAG_PREFIX)) {
      const taskId = tag.slice(TASK_TAG_PREFIX.length).trim();
      if (taskId) {
        return taskId;
      }
    }
  }
  return null;
}

/** Replaces any existing link, so a ticket never carries two agent threads. */
export function withTicketTaskId(
  tags: readonly string[] | undefined,
  taskId: string,
): string[] {
  const kept = (tags ?? []).filter(
    (tag) => !tag.toLowerCase().startsWith(TASK_TAG_PREFIX),
  );
  return [...kept, `${TASK_TAG_PREFIX}${taskId}`];
}

const MAX_PROMPT_MESSAGES = 20;
const MAX_PROMPT_MESSAGE_LENGTH = 2_000;

function truncate(text: string, limit: number): string {
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

/**
 * The brief an agent gets when a thread starts on a ticket: what the ticket is,
 * then the conversation so far, then what the engineer asked.
 *
 * Only the tail of a long thread is included. The opening messages of a support
 * conversation are usually the least useful part by the time an agent is
 * involved, and an unbounded transcript crowds out the actual request.
 */
export function buildTicketAgentPrompt(
  ticket: SupportTicket,
  messages: readonly SupportTicketMessage[],
  request: string,
): string {
  const facts = [
    `Ticket #${ticket.ticket_number}`,
    `Channel: ${ticket.channel_source}`,
    `Status: ${ticket.status ?? "new"}`,
    ticket.priority ? `Priority: ${ticket.priority}` : null,
    ticket.github_repo && ticket.github_issue_number
      ? `Linked issue: ${ticket.github_repo}#${ticket.github_issue_number}`
      : null,
  ].filter((line): line is string => line !== null);

  const transcript = messages
    .slice(-MAX_PROMPT_MESSAGES)
    .map((message) => {
      const author =
        message.author_type === "support"
          ? `${message.author_name} (support)`
          : message.author_type === "AI"
            ? `${message.author_name} (AI)`
            : `${message.author_name} (customer)`;
      const visibility = message.is_private ? " [internal note]" : "";
      return `${author}${visibility}: ${truncate(
        message.content,
        MAX_PROMPT_MESSAGE_LENGTH,
      )}`;
    })
    .join("\n\n");

  return [
    "You are helping a PostHog support engineer with a customer support ticket.",
    facts.join("\n"),
    transcript ? `Conversation so far:\n\n${transcript}` : null,
    `The engineer asks:\n\n${request}`,
  ]
    .filter((section): section is string => section !== null)
    .join("\n\n---\n\n");
}
