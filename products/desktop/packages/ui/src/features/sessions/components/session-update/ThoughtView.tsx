import { Brain } from "@phosphor-icons/react";
import { memo } from "react";
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
        {isLoading ? "Thinking" : "Thought"}
      </ToolRow>
    </div>
  );
});
