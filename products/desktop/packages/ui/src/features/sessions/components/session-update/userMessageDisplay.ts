import {
  type InjectedBlock,
  splitInjectedBlocks,
} from "@posthog/core/editor/injectedBlocks";
import { resolveMessageAttachments } from "@posthog/core/sessions/promptContent";
import type { UserMessageAttachment } from "@posthog/ui/features/sessions/userMessageTypes";
import { collapsePiSkillInvocation } from "./piSkillInvocation";

export interface UserMessageParts {
  blocks: InjectedBlock[];
  displayContent: string;
  attachments: UserMessageAttachment[];
}

export function splitUserMessage(
  content: string,
  attachments: UserMessageAttachment[] = [],
): UserMessageParts {
  const { blocks, text } = splitInjectedBlocks(content);
  const resolved = resolveMessageAttachments(
    collapsePiSkillInvocation(text),
    attachments,
  );
  return {
    blocks,
    displayContent: resolved.text,
    attachments: resolved.attachments,
  };
}

export function userMessageDisplayText(content: string): string {
  return splitUserMessage(content).displayContent;
}
