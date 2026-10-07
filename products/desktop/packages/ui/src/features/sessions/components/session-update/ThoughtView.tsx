import { Brain } from "@phosphor-icons/react";
import { memo } from "react";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";
import { ToolRow } from "./ToolRow";
import { ContentPre } from "./toolCallUtils";

interface ThoughtViewProps {
  content: string;
  isLoading: boolean;
}

export const ThoughtView = memo(function ThoughtView({
  content,
  isLoading,
}: ThoughtViewProps) {
  const hasContent = content.trim().length > 0;
  // Chat-thread chrome uses past tense after a thought completes. The standalone fallback retains
  // "Thinking" when chat-thread chrome is unavailable.
  const chatChrome = useChatThreadChrome();

  // An empty thought that's done streaming is pure noise — a bare "Thinking"
  // header with nothing under it. Only show it while content is still arriving.
  if (!hasContent && !isLoading) return null;

  return (
    <div>
      <ToolRow
        icon={Brain}
        isLoading={isLoading}
        content={hasContent ? <ContentPre>{content}</ContentPre> : undefined}
      >
        {chatChrome && !isLoading ? "Thought" : "Thinking"}
      </ToolRow>
    </div>
  );
});
