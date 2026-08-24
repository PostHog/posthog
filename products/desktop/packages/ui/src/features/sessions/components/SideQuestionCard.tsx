import { ChatCircleDots, Spinner, X } from "@phosphor-icons/react";
import { useSideQuestionStore } from "@posthog/ui/features/sessions/sideQuestionStore";
import { Box, Flex, IconButton, Text, Tooltip } from "@radix-ui/themes";
import { MarkdownRenderer } from "../../editor/components/MarkdownRenderer";

interface SideQuestionCardProps {
  taskId: string;
  /** The task's current run. An entry asked against a prior run is hidden. */
  taskRunId?: string;
}

/**
 * Ephemeral "/btw" side-question card pinned above the composer. The exchange
 * lives only in view state — it is never part of the session transcript — so
 * dismissing it leaves no trace.
 */
export function SideQuestionCard({ taskId, taskRunId }: SideQuestionCardProps) {
  const entry = useSideQuestionStore((s) => s.byTaskId[taskId]);
  const dismiss = useSideQuestionStore((s) => s.dismiss);

  if (!entry || entry.taskRunId !== taskRunId) return null;

  return (
    <Box className="mb-2 rounded-lg border border-gray-5 bg-card px-3 py-2">
      <Flex align="center" gap="2">
        <ChatCircleDots size={14} className="shrink-0 text-gray-9" />
        <Text
          title={entry.question}
          className="min-w-0 flex-1 truncate font-medium text-[13px] text-gray-11"
        >
          {entry.question}
        </Text>
        <Tooltip content="Dismiss">
          <IconButton
            size="1"
            variant="ghost"
            color="gray"
            aria-label="Dismiss side question"
            onClick={() => dismiss(taskId)}
          >
            <X size={12} />
          </IconButton>
        </Tooltip>
      </Flex>
      <Box className="mt-1 pl-6" role="status" aria-live="polite">
        {entry.status === "pending" && (
          <Flex align="center" gap="2">
            <Spinner size={14} className="animate-spin text-gray-9" />
            <Text className="text-[13px] text-gray-9">Answering…</Text>
          </Flex>
        )}
        {entry.status === "done" && (
          <Box className="max-h-64 overflow-y-auto text-[13px] text-gray-12">
            <MarkdownRenderer content={entry.answer} />
          </Box>
        )}
        {entry.status === "error" && (
          <Text className="text-[13px] text-red-11">{entry.error}</Text>
        )}
      </Box>
    </Box>
  );
}
