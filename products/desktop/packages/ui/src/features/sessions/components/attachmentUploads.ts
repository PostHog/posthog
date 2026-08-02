import type { FileAttachment } from "@posthog/core/message-editor/content";

export function getAddedAttachments(
  previousIds: ReadonlySet<string>,
  attachments: FileAttachment[],
): FileAttachment[] {
  return attachments.filter(({ id }) => !previousIds.has(id));
}
