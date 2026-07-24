import { CaretDown, CaretRight } from "@phosphor-icons/react";
import { CHAT_CONTENT_MAX_WIDTH } from "@posthog/ui/features/sessions/constants";
import type { Plan } from "@posthog/ui/features/sessions/types";
import {
  StepIcon,
  StepList,
  type StepStatus,
} from "@posthog/ui/primitives/StepList";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useMemo, useState } from "react";

function planEntriesToSteps(plan: Plan) {
  return plan.entries.map((entry) => ({
    key: entry.content,
    label: entry.content,
    status: entry.status as StepStatus,
  }));
}

interface PlanStatusBarProps {
  plan: Plan | null;
}

export function PlanStatusBar({ plan }: PlanStatusBarProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const stats = useMemo(() => {
    if (!plan?.entries?.length) return null;

    const completed = plan.entries.filter(
      (e) => e.status === "completed",
    ).length;
    const total = plan.entries.length;
    const inProgress = plan.entries.find((e) => e.status === "in_progress");
    const allCompleted = completed === total;

    return { completed, total, inProgress, allCompleted };
  }, [plan]);

  // Hide if no plan or all tasks completed
  if (!stats || stats.allCompleted) return null;

  return (
    <Box
      className="cursor-pointer border-gray-4 border-t bg-gray-2"
      onClick={() => setIsExpanded(!isExpanded)}
    >
      <Box className="mx-auto" style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}>
        <Flex align="center" gap="2" className="px-3 py-2">
          {isExpanded ? (
            <CaretDown size={12} className="text-gray-9" />
          ) : (
            <CaretRight size={12} className="text-gray-9" />
          )}
          <Text color="gray" className="whitespace-nowrap text-[13px]">
            {stats.completed}/{stats.total} completed
          </Text>
          {stats.inProgress && (
            <>
              <Text color="gray" className="text-[13px]">
                •
              </Text>
              <StepIcon status="in_progress" />
              <Text className="truncate text-[13px] text-gray-11">
                {stats.inProgress.content}
              </Text>
            </>
          )}
        </Flex>

        {isExpanded && plan && (
          <Box className="border-gray-4 border-t px-3 pt-2 pb-2">
            <StepList steps={planEntriesToSteps(plan)} size="1" />
          </Box>
        )}
      </Box>
    </Box>
  );
}
