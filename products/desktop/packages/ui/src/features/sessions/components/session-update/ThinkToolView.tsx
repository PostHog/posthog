import { Brain } from "@phosphor-icons/react";
import { ToolRow } from "./ToolRow";
import {
  ContentPre,
  getContentText,
  type ToolViewProps,
  useToolCallStatus,
} from "./toolCallUtils";

export function ThinkToolView({
  toolCall,
  turnCancelled,
  turnComplete,
}: ToolViewProps) {
  const { status, content, title } = toolCall;
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );

  const thinkingContent = getContentText(content) ?? "";
  const hasContent = thinkingContent.trim().length > 0;

  return (
    <ToolRow
      icon={Brain}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      content={
        hasContent ? <ContentPre>{thinkingContent}</ContentPre> : undefined
      }
    >
      {title || "Thinking"}
    </ToolRow>
  );
}
