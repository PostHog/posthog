import { stripTrailingAttachmentSummary } from "@posthog/core/editor/cloud-prompt";
import { extractCanvasInstructions } from "@posthog/ui/features/sessions/components/session-update/canvasInstructions";
import { extractChannelContext } from "@posthog/ui/features/sessions/components/session-update/channelContext";
import { extractCustomInstructions } from "@posthog/ui/features/sessions/components/session-update/customInstructions";

export const PROMPT_RECALL_HINT_KEY = "recall-message-nav";

export interface RecallableMessage {
  id: string;
  content: string;
}

export type PromptRecallDirection = -1 | 1;

export type PromptRecallAction =
  | { kind: "recall"; id: string; fresh: boolean }
  | { kind: "exit" };

export type PromptRecallResult =
  | { kind: "recall"; text: string; fresh: boolean }
  | { kind: "exit" };

export type PromptRecallHandler = (
  direction: PromptRecallDirection,
) => PromptRecallResult | null;

export function promptRecallStep(
  sentPromptIds: string[],
  currentId: string | null,
  direction: PromptRecallDirection,
): PromptRecallAction | null {
  if (sentPromptIds.length === 0) return null;

  const currentIndex = currentId ? sentPromptIds.indexOf(currentId) : -1;

  if (direction === -1) {
    const previousIndex =
      currentIndex === -1
        ? sentPromptIds.length - 1
        : Math.max(0, currentIndex - 1);
    const id = sentPromptIds[previousIndex];
    return id ? { kind: "recall", id, fresh: currentIndex === -1 } : null;
  }

  // Down only cycles toward newer prompts while already recalling; otherwise
  // the caret is just resting at the end of the input and the key stays inert.
  if (currentIndex === -1) return null;
  if (currentIndex >= sentPromptIds.length - 1) {
    return { kind: "exit" };
  }
  const id = sentPromptIds[currentIndex + 1];
  return id ? { kind: "recall", id, fresh: false } : null;
}

// A stored prompt can carry blocks folded in at send time that the user never
// typed (channel CONTEXT.md, canvas instructions, personalization, a trailing
// attachment summary); recall returns only what the user wrote.
function stripInjectedPromptBlocks(content: string): string {
  const withoutChannel = extractChannelContext(content)?.stripped ?? content;
  const withoutCanvas =
    extractCanvasInstructions(withoutChannel)?.stripped ?? withoutChannel;
  const withoutInstructions =
    extractCustomInstructions(withoutCanvas)?.stripped ?? withoutCanvas;
  return stripTrailingAttachmentSummary(withoutInstructions);
}

export function resolvePromptRecall(
  messages: RecallableMessage[],
  currentId: string | null,
  direction: PromptRecallDirection,
): { result: PromptRecallResult | null; nextId: string | null } {
  const action = promptRecallStep(
    messages.map((message) => message.id),
    currentId,
    direction,
  );
  if (!action) return { result: null, nextId: currentId };
  if (action.kind === "exit") return { result: { kind: "exit" }, nextId: null };
  const message = messages.find((entry) => entry.id === action.id);
  if (!message) return { result: null, nextId: currentId };
  return {
    result: {
      kind: "recall",
      text: stripInjectedPromptBlocks(message.content),
      fresh: action.fresh,
    },
    nextId: action.id,
  };
}
