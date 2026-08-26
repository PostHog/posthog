import { ChatCircleIcon } from "@phosphor-icons/react";
import {
  Button,
  Dot,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import {
  findContinuableImplementationTask,
  findLatestDiscussionTask,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";

const HEADER_ACTION_CLASS = "h-7 gap-1.5 px-2.5 text-[12px]";

export function ReportChatToggle({ report }: { report: SignalReport }) {
  const chatOpen = useReportChatPanelStore((state) => state.open);
  const setChatOpen = useReportChatPanelStore((state) => state.setOpen);
  const startedTaskId = useReportChatPanelStore(
    (state) => state.startedTaskIdByReport[report.id] ?? null,
  );
  const { data: reportTasks } = useReportTasks(report.id, report.status);
  const hasConversation =
    startedTaskId !== null ||
    findContinuableImplementationTask(reportTasks) !== null ||
    findLatestDiscussionTask(reportTasks) !== null;
  const actionLabel = chatOpen ? "Close chat" : "Open chat";
  const accessibleLabel = hasConversation
    ? `${actionLabel} (existing conversation)`
    : actionLabel;

  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <Button
            type="button"
            variant={chatOpen ? "primary" : "outline"}
            size="xs"
            className={HEADER_ACTION_CLASS}
            aria-label={accessibleLabel}
            aria-pressed={chatOpen}
            data-attr="report-chat-toggle"
            onClick={() => setChatOpen(!chatOpen)}
          />
        }
      >
        <ChatCircleIcon />
        Chat
        {hasConversation && <Dot variant="info" />}
      </TooltipTrigger>
      <TooltipContent side="bottom">{accessibleLabel}</TooltipContent>
    </Tooltip>
  );
}
