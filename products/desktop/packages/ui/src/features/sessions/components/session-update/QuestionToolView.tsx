import { ChatCircle, CheckCircle } from "@phosphor-icons/react";
import { Text } from "@radix-ui/themes";
import { ToolRow } from "./ToolRow";
import {
  getContentText,
  type ToolViewProps,
  useToolCallStatus,
} from "./toolCallUtils";

export function QuestionToolView({
  toolCall,
  turnCancelled,
  turnComplete,
}: ToolViewProps) {
  const { status, content, title } = toolCall;
  const { isLoading, isComplete, isFailed, wasCancelled } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );

  const answerText = getContentText(content);
  const showAnswer = isComplete && !!answerText;

  return (
    <ToolRow
      icon={ChatCircle}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      defaultOpen
      content={
        showAnswer ? (
          <div className="flex items-center gap-2 px-3 py-2">
            <CheckCircle size={14} weight="fill" className="text-green-9" />
            <Text className="text-[13px] text-green-11">{answerText}</Text>
          </div>
        ) : undefined
      }
    >
      {title || "Question"}
    </ToolRow>
  );
}
