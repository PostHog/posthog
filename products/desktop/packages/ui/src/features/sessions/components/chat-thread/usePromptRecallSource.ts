import {
  type PromptRecallHandler,
  type RecallableMessage,
  resolvePromptRecall,
} from "@posthog/ui/features/sessions/components/chat-thread/composerPromptRecall";
import { type RefObject, useCallback, useEffect, useRef } from "react";

export function usePromptRecallSource(
  messages: RecallableMessage[],
  promptRecallRef: RefObject<PromptRecallHandler | null> | undefined,
): void {
  // Read at keypress time so the handler registered in the ref effect never
  // acts on a stale snapshot (the effect runs after paint, and key repeats
  // can outpace re-renders).
  const messagesRef = useRef(messages);
  messagesRef.current = messages;

  // Recall position is invisible (no highlight, no scrolling), so a plain ref
  // is enough. A newly sent prompt resets it so the next Up starts from it.
  const recallMessageIdRef = useRef<string | null>(null);
  const prevMessageCountRef = useRef(messages.length);
  if (messages.length > prevMessageCountRef.current) {
    recallMessageIdRef.current = null;
  }
  prevMessageCountRef.current = messages.length;

  const recallFromComposer = useCallback<PromptRecallHandler>((direction) => {
    const { result, nextId } = resolvePromptRecall(
      messagesRef.current,
      recallMessageIdRef.current,
      direction,
    );
    recallMessageIdRef.current = nextId;
    return result;
  }, []);

  useEffect(() => {
    if (!promptRecallRef) return;
    promptRecallRef.current = recallFromComposer;
    return () => {
      promptRecallRef.current = null;
    };
  }, [promptRecallRef, recallFromComposer]);
}
