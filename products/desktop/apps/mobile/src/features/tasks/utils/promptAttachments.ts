import { extractPromptDisplayContent } from "@posthog/core/sessions/promptContent";
import { isRasterImageFile } from "@posthog/shared";
import type { SessionEvent, SessionNotificationAttachment } from "../types";

interface PromptMessage {
  method?: string;
  params?: { prompt?: unknown[] };
}

export interface PromptAttachmentGroup {
  text: string;
  attachments: SessionNotificationAttachment[];
}

/** `ContentBlock[]`, without making mobile depend on the ACP SDK for a type. */
type PromptBlocks = Parameters<typeof extractPromptDisplayContent>[0];

export function extractSessionPromptAttachments(
  message: unknown,
): PromptAttachmentGroup | null {
  const msg = message as PromptMessage | undefined;
  if (msg?.method !== "session/prompt") return null;
  const prompt = msg.params?.prompt;
  if (!Array.isArray(prompt)) return null;

  const { text, attachments } = extractPromptDisplayContent(
    prompt as PromptBlocks,
    { filterHidden: true },
  );
  if (attachments.length === 0) return null;

  return {
    text,
    attachments: attachments.map((ref) => ({
      // Image-vs-chip rendering is a mobile concern; the shared refs don't
      // carry a kind.
      kind: isRasterImageFile(ref.label) ? "image" : "document",
      // Inline base64 images have no fetchable uri of their own — their data:
      // preview is the only thing that can be rendered.
      uri: ref.previewUrl ?? ref.id,
      fileName: ref.label,
      ...(ref.cloudArtifact ? { cloudArtifact: ref.cloudArtifact } : {}),
    })),
  };
}

/**
 * S3-backed snapshots replay user turns as text-only `user_message_chunk`
 * events, dropping the attachment metadata. The `session/prompt` requests in the
 * same log still carry the cloud artifact references, so reattach them by
 * matching prompt text (FIFO on ties) to keep historical images renderable.
 */
export function reinjectPromptAttachments(events: SessionEvent[]): void {
  const pending: PromptAttachmentGroup[] = [];
  for (const event of events) {
    if (event.type === "acp_message") {
      const group = extractSessionPromptAttachments(event.message);
      if (group) pending.push(group);
      continue;
    }
    const update = event.notification?.update;
    if (update?.sessionUpdate !== "user_message_chunk") continue;
    if (update.attachments && update.attachments.length > 0) continue;
    const text = update.content?.text ?? "";
    const idx = pending.findIndex((group) => group.text === text);
    if (idx < 0) continue;
    update.attachments = pending[idx].attachments;
    pending.splice(idx, 1);
  }
}
