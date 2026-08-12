import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";

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

export function isTicketTaskTag(tag: string): boolean {
  return tag.toLowerCase().startsWith(TASK_TAG_PREFIX);
}

export function withTicketTaskId(
  tags: readonly string[] | undefined,
  taskId: string,
): string[] {
  return [
    ...(tags ?? []).filter((tag) => !isTicketTaskTag(tag)),
    `${TASK_TAG_PREFIX}${taskId}`,
  ];
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
