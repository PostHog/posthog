import type { PendingAttachment } from "./attachments/types";

export interface ComposerContent {
  text: string;
  attachments: PendingAttachment[];
}

export function isComposerEmpty(content: ComposerContent): boolean {
  return content.text.trim().length === 0 && content.attachments.length === 0;
}

interface SubmitComposerMessageOptions {
  submitted: ComposerContent;
  clear: () => void;
  send: () => Promise<boolean>;
  isLatestSubmission: () => boolean;
  isEmpty: () => boolean;
  restore: (content: ComposerContent) => void;
}

export async function submitComposerMessage({
  submitted,
  clear,
  send,
  isLatestSubmission,
  isEmpty,
  restore,
}: SubmitComposerMessageOptions): Promise<void> {
  clear();

  let sent = false;
  try {
    sent = await send();
  } catch {
    sent = false;
  }

  if (!sent && isLatestSubmission() && isEmpty()) {
    restore(submitted);
  }
}
