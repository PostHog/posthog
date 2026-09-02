import type { CloudPromptBlock, PendingAttachment } from "./types";

export interface AttachmentPreparer {
  prepare(attachment: PendingAttachment): Promise<CloudPromptBlock>;
  forget(id: string): void;
}

export function createAttachmentPreparer(
  build: (attachment: PendingAttachment) => Promise<CloudPromptBlock>,
): AttachmentPreparer {
  const cache = new Map<string, Promise<CloudPromptBlock>>();

  return {
    prepare(attachment) {
      const existing = cache.get(attachment.id);
      if (existing) return existing;

      const pending = build(attachment).catch((error) => {
        cache.delete(attachment.id);
        throw error;
      });
      cache.set(attachment.id, pending);
      return pending;
    },
    forget(id) {
      cache.delete(id);
    },
  };
}
