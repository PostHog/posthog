import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";

const TASK_TAG_PREFIX = "ai-task:";
const MACHINE_TAG_PREFIXES = [
  TASK_TAG_PREFIX,
  "code-task:",
  "max-conversation:",
];

export function readTicketTaskId(
  tags: readonly string[] | undefined,
): string | null {
  for (const prefix of [TASK_TAG_PREFIX, "code-task:"]) {
    for (const tag of tags ?? []) {
      if (tag.toLowerCase().startsWith(prefix)) {
        const taskId = tag.slice(prefix.length).trim();
        if (taskId) {
          return taskId;
        }
      }
    }
  }
  return null;
}

export function isTicketTaskTag(tag: string): boolean {
  const lower = tag.toLowerCase();
  return MACHINE_TAG_PREFIXES.some((prefix) => lower.startsWith(prefix));
}

export function withoutTicketTaskId(
  tags: readonly string[] | undefined,
): string[] {
  return (tags ?? []).filter((tag) => !isTicketTaskTag(tag));
}

export function withTicketTaskId(
  tags: readonly string[] | undefined,
  taskId: string,
): string[] {
  return [...withoutTicketTaskId(tags), `${TASK_TAG_PREFIX}${taskId}`];
}

const MAX_PROMPT_MESSAGES = 20;

export function buildTicketAgentPrompt(
  ticket: SupportTicket,
  messages: readonly SupportTicketMessage[],
  request: string,
): string {
  const transcript = messages
    .slice(-MAX_PROMPT_MESSAGES)
    .map((message) => `${message.author_name}: ${message.content}`)
    .join("\n\n");

  return [
    `PostHog support ticket #${ticket.ticket_number} (${ticket.channel_source}).`,
    transcript,
    request,
  ]
    .filter(Boolean)
    .join("\n\n---\n\n");
}
