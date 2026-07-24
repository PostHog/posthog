import { CaretDown, CaretRight, CheckCircle } from "@phosphor-icons/react";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { PlanContent } from "../../../permissions/PlanContent";
import {
  flattenSelectOptions,
  useModelConfigOptionForTask,
} from "../../sessionStore";
import { useSessionTaskId } from "../../useSessionTaskId";
import { ModelSelector } from "../ModelSelector";
import { type ToolViewProps, useToolCallStatus } from "./toolCallUtils";

export function PlanApprovalView({
  toolCall,
  turnCancelled,
  turnComplete,
}: ToolViewProps) {
  const { content } = toolCall;
  const { isComplete, isFailed, wasCancelled } = useToolCallStatus(
    toolCall.status,
    turnCancelled,
    turnComplete,
  );
  const [isPlanExpanded, setIsPlanExpanded] = useState(false);
  const taskId = useSessionTaskId();
  const modelOption = useModelConfigOptionForTask(taskId ?? undefined);
  const hasModelSelector =
    modelOption?.type === "select" &&
    flattenSelectOptions(modelOption.options).length > 0;
  const rawInput = toolCall.rawInput as
    | { historical?: boolean; plan?: string }
    | undefined;
  const isHistoricalPlan = rawInput?.historical === true;

  const planText = useMemo(() => {
    if (content?.length) {
      const textContent = content.find((c) => c.type === "content");
      if (textContent && "content" in textContent) {
        const inner = textContent.content as
          | { type?: string; text?: string }
          | undefined;
        if (inner?.type === "text" && inner.text) {
          return inner.text;
        }
      }
    }
    return rawInput?.plan ?? null;
  }, [content, rawInput?.plan]);

  const wasNotApproved = isFailed || wasCancelled;
  const showResult = isHistoricalPlan || isComplete || wasNotApproved;
  const canTogglePlan = showResult && !!planText;
  const planContentId = `plan-content-${toolCall.toolCallId}`;

  if (!planText && !showResult) return null;

  const statusContent = isHistoricalPlan ? (
    <Text className="text-[13px] text-gray-11">Plan</Text>
  ) : isComplete ? (
    <>
      <CheckCircle size={14} weight="fill" className="text-green-9" />
      <Text className="text-[13px] text-green-11">
        Plan approved — proceeding with implementation
      </Text>
    </>
  ) : wasNotApproved ? (
    <Text className="text-[13px] text-gray-10">(Plan not approved)</Text>
  ) : null;

  return (
    <Box className="my-3">
      {!showResult && planText && (
        <>
          {taskId && hasModelSelector && (
            <Flex align="center" gap="2" className="mb-2 px-1">
              <Text className="text-[12px] text-gray-11">Model</Text>
              <ModelSelector taskId={taskId} />
            </Flex>
          )}
          <PlanContent id={toolCall.toolCallId} plan={planText} />
        </>
      )}

      {showResult && (
        <Box>
          {canTogglePlan ? (
            <button
              type="button"
              onClick={() => setIsPlanExpanded((v) => !v)}
              aria-expanded={isPlanExpanded}
              aria-controls={planContentId}
              className="flex items-center gap-2 rounded-sm px-1 text-left hover:bg-gray-3"
            >
              {isPlanExpanded ? (
                <CaretDown size={12} className="text-gray-10" />
              ) : (
                <CaretRight size={12} className="text-gray-10" />
              )}
              {statusContent}
              <Text className="text-[13px] text-gray-10">
                · {isPlanExpanded ? "hide plan" : "show plan"}
              </Text>
            </button>
          ) : (
            <Flex align="center" gap="2" className="px-1">
              {statusContent}
            </Flex>
          )}

          {canTogglePlan && isPlanExpanded && (
            <Box id={planContentId} className="mt-2">
              <PlanContent id={toolCall.toolCallId} plan={planText} />
            </Box>
          )}
        </Box>
      )}
    </Box>
  );
}
