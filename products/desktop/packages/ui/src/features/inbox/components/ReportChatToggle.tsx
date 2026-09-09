import { ChatCircleIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import {
  findContinuableImplementationTask,
  findLatestDiscussionTask,
  findPendingStartedTaskId,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";

export function ReportChatToggle({ report }: { report: SignalReport }) {
  const chatOpen = useReportChatPanelStore((state) => state.open);
  const setChatOpen = useReportChatPanelStore((state) => state.setOpen);
  const startedTaskId = useReportChatPanelStore(
    (state) => state.startedTaskIdByReport[report.id] ?? null,
  );
  const { data: reportTasks } = useReportTasks(report.id, report.status);
  const hasConversation =
    findPendingStartedTaskId(reportTasks, startedTaskId) !== null ||
    findContinuableImplementationTask(reportTasks) !== null ||
    findLatestDiscussionTask(reportTasks) !== null;
  const actionLabel = chatOpen
    ? "Close chat"
    : hasConversation
      ? "Open existing chat"
      : "Open chat";

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            variant={chatOpen ? "primary" : "outline"}
            size="xs"
            className="relative h-7 gap-1.5 px-2.5 text-[12px]"
            aria-label={actionLabel}
            aria-pressed={chatOpen}
            data-attr="report-chat-toggle"
            onClick={() => setChatOpen(!chatOpen)}
          />
        }
      >
        <span aria-hidden data-slot="chat-icon" className="flex items-center">
          <ChatCircleIcon size={14} />
        </span>
        Chat
        {hasConversation && (
          <span
            aria-hidden
            data-slot="conversation-indicator"
            className="-top-1 -right-1 absolute size-2 rounded-full bg-(--blue-9) ring-2 ring-chrome"
          />
        )}
      </TooltipTrigger>
      <TooltipContent side="bottom">{actionLabel}</TooltipContent>
    </Tooltip>
  );
}
