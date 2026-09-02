import {
  isUploadArtifactCall,
  readCreatedPrUrl as readCreatedPrUrlFromCall,
  readUploadedArtifactName,
} from "@posthog/core/sessions/inlineArtifacts";
import { getContentText } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import type { ToolCall } from "@posthog/ui/features/sessions/types";

export { isUploadArtifactCall, readUploadedArtifactName };

function toolCallOutputText(toolCall: ToolCall): string {
  const content = getContentText(toolCall.content) ?? "";
  const raw = toolCall.rawOutput;
  return typeof raw === "string" ? `${content}\n${raw}` : content;
}

/** The pull request a tool call just opened, or null. */
export function readCreatedPrUrl(toolCall: ToolCall): string | null {
  return readCreatedPrUrlFromCall({
    status: toolCall.status ?? undefined,
    meta: toolCall._meta,
    rawInput: toolCall.rawInput,
    outputText: toolCallOutputText(toolCall),
  });
}

/** Whether a tool call draws an artifact card, which never folds into a tool group. */
export function hasInlineArtifact(toolCall: ToolCall): boolean {
  return (
    isUploadArtifactCall(toolCall._meta) || readCreatedPrUrl(toolCall) !== null
  );
}
