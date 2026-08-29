import {
  ArrowsOutSimpleIcon,
  ChatCircleIcon,
  XIcon,
} from "@phosphor-icons/react";
import {
  isContentEmpty,
  textToContent,
} from "@posthog/core/message-editor/content";
import { Button, Spinner, Textarea } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useDiscussReport } from "@posthog/ui/features/inbox/hooks/useDiscussReport";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import {
  findContinuableImplementationTask,
  findLatestDiscussionTask,
  findPendingStartedTaskId,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import { useOpenTask } from "@posthog/ui/router/useOpenTask";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

const isMac =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

interface ReportChatSidebarProps {
  report: SignalReport;
}

/**
 * The report's conversation, docked beside the report so reading and asking
 * happen on one screen (navigating away to a task page made people lose the
 * report they were asking about). One conversation per report: the dock binds
 * to the report's live implementation task when one exists (continuing the
 * fix IS chatting with the report), then to a task started this session, then
 * to the existing discussion; only the first question on a task-less report
 * creates one. The full task page stays one click away in the header.
 */
export function ReportChatSidebar({ report }: ReportChatSidebarProps) {
  const width = useReportChatPanelStore((s) => s.width);
  const setWidth = useReportChatPanelStore((s) => s.setWidth);
  const setOpen = useReportChatPanelStore((s) => s.setOpen);
  const startedTaskId = useReportChatPanelStore(
    (s) => s.startedTaskIdByReport[report.id] ?? null,
  );
  const [isResizing, setIsResizing] = useState(false);

  // The durable association arrives via the report's task_run artefacts; a
  // task started seconds ago is bridged by the store until it does. The session
  // bridge wins so a newly started canvas, fix, or discussion takes the dock
  // over immediately, then expires once the durable association arrives.
  const { data: reportTasks, isLoading: tasksLoading } = useReportTasks(
    report.id,
    report.status,
  );
  const taskId =
    findPendingStartedTaskId(reportTasks, startedTaskId) ??
    findContinuableImplementationTask(reportTasks)?.id ??
    findLatestDiscussionTask(reportTasks)?.id ??
    null;
  const openTask = useOpenTask();
  // Same query the conversation issues; react-query dedupes them.
  const { data: boundTask } = useQuery({
    ...taskDetailQuery(taskId ?? ""),
    enabled: !!taskId,
  });

  return (
    <ResizableSidebar
      open
      width={width}
      setWidth={setWidth}
      isResizing={isResizing}
      setIsResizing={setIsResizing}
      side="right"
    >
      <div className="flex h-full min-w-0 flex-col border-border border-l bg-gray-1">
        <div className="flex h-10 shrink-0 items-center justify-between border-b bg-chrome pr-2 pl-3">
          <span className="flex items-center gap-1.5 font-medium text-[14px] text-gray-12">
            <ChatCircleIcon size={14} />
            Chat
          </span>
          <span className="flex items-center gap-1">
            {boundTask && (
              <Button
                size="icon-sm"
                variant="default"
                aria-label="Open the full task"
                title="Open the full task"
                onClick={() => void openTask(boundTask)}
              >
                <ArrowsOutSimpleIcon size={14} />
              </Button>
            )}
            <Button
              size="icon-sm"
              variant="default"
              aria-label="Close chat"
              onClick={() => setOpen(false)}
            >
              <XIcon size={14} />
            </Button>
          </span>
        </div>
        <div className="min-h-0 flex-1">
          {taskId ? (
            <ReportChatConversation report={report} taskId={taskId} />
          ) : tasksLoading ? (
            // Offering the starter before the task lookup resolves invites a
            // duplicate conversation on a report that already has one.
            <div className="flex h-full items-center justify-center">
              <Spinner />
            </div>
          ) : (
            <ReportChatStarter report={report} />
          )}
        </div>
      </div>
    </ResizableSidebar>
  );
}

// Resolves the discussion's task record and renders its live session chat —
// the same embedded view the canvas dock uses, so steering, queueing, and
// follow-ups on a finished run all behave like they do elsewhere.
function ReportChatConversation({
  report,
  taskId,
}: {
  report: SignalReport;
  taskId: string;
}) {
  const reportId = report.id;
  const { data: task } = useQuery(taskDetailQuery(taskId));

  const pendingQuote = useReportChatPanelStore(
    (s) => s.pendingQuoteByReport[reportId] ?? null,
  );
  const takePendingQuote = useReportChatPanelStore((s) => s.takePendingQuote);
  const { insertPendingContent, getDraft, requestFocus } = useDraftStore(
    (s) => s.actions,
  );
  // A highlighted passage is appended into the session composer, after anything
  // already typed rather than replacing it. Inserting (rather than rewriting the
  // draft) keeps chips and file attachments the user already added, and reaches
  // the live editor even when it already holds text.
  useEffect(() => {
    if (!pendingQuote || !task) return;
    const quote = takePendingQuote(reportId);
    if (!quote) return;
    const separator = isContentEmpty(getDraft(taskId)) ? "" : "\n\n";
    insertPendingContent(taskId, textToContent(`${separator}${quote}`));
    requestFocus(taskId);
  }, [
    pendingQuote,
    task,
    taskId,
    reportId,
    getDraft,
    insertPendingContent,
    takePendingQuote,
    requestFocus,
  ]);

  if (!task) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return <EmbeddedSessionView task={task} />;
}

// The report has no conversation yet: one question starts it, with the full
// report and its evidence inlined as the agent's context.
function ReportChatStarter({ report }: { report: SignalReport }) {
  const queryClient = useQueryClient();
  const fireAction = useReportActionTracker(report);
  const rememberStartedTask = useReportChatPanelStore(
    (s) => s.rememberStartedTask,
  );
  const pendingQuote = useReportChatPanelStore(
    (s) => s.pendingQuoteByReport[report.id] ?? null,
  );
  const takePendingQuote = useReportChatPanelStore((s) => s.takePendingQuote);
  const starterDraft = useReportChatPanelStore(
    (s) => s.starterDraftByReport[report.id] ?? "",
  );
  const setStarterDraft = useReportChatPanelStore((s) => s.setStarterDraft);
  const clearStarterDraft = useReportChatPanelStore((s) => s.clearStarterDraft);

  // Taken atomically so a double-fired effect can't paste the quote twice.
  useEffect(() => {
    if (!pendingQuote) return;
    const quote = takePendingQuote(report.id);
    if (!quote) return;
    const current =
      useReportChatPanelStore.getState().starterDraftByReport[report.id] ?? "";
    setStarterDraft(
      report.id,
      current.trim() ? `${current.trimEnd()}\n\n${quote}` : quote,
    );
  }, [pendingQuote, takePendingQuote, setStarterDraft, report.id]);

  // Discussions file into the report's space, or #general when it has none —
  // a task without a channel shows in no space's sidebar at all.
  const { generalChannel } = useTaskChannels();
  const taskChannelId = report.channel_id ?? generalChannel?.id ?? null;

  const { discussReport, isDiscussing } = useDiscussReport({
    report,
    channelId: taskChannelId,
    redirectOnSuccess: false,
    onTaskCreated: (task) => {
      // Seed the detail cache with the task we already hold so the panel's
      // useQuery resolves from cache instead of firing a GET that can 404 while
      // the API catches up (mirrors openTask, which this non-redirect path skips).
      queryClient.setQueryData(taskDetailQuery(task.id).queryKey, task);
      rememberStartedTask(report.id, task.id);
      // The task exists now, so the draft has served its purpose. Clearing only
      // here (not on submit) keeps a failed creation's text for another try.
      clearStarterDraft(report.id);
      // The task_run artefact is written with the task, so a refetch picks up
      // the durable association right away.
      void queryClient.invalidateQueries({
        queryKey: ["inbox", "report-tasks", report.id],
      });
    },
  });

  const submit = useCallback(() => {
    const trimmed = starterDraft.trim();
    if (!trimmed || isDiscussing) return;
    // Only whether a question was asked — never the text. A quoted passage can
    // be verbatim report content (customer data, code, identifiers), so it must
    // not reach analytics.
    fireAction("discuss", { has_question: true });
    void discussReport(trimmed);
  }, [starterDraft, isDiscussing, discussReport, fireAction]);

  return (
    <div className="flex h-full flex-col justify-between gap-3 p-3">
      <div className="flex flex-col gap-1 pt-1">
        <span className="text-[13px] text-gray-11">
          The agent joins with the full report and its evidence already in
          context. Highlight any part of the report to quote it here.
        </span>
      </div>
      <form
        className="flex flex-col gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <Textarea
          aria-label="Question about this report"
          autoFocus
          placeholder="Ask about this report…"
          rows={5}
          value={starterDraft}
          onChange={(event) => setStarterDraft(report.id, event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <div className="flex items-center justify-between gap-2">
          <span className="text-[12px] text-gray-10">
            {isMac ? "⌘↵" : "Ctrl+↵"} to send
          </span>
          <Button
            type="submit"
            variant="primary"
            size="sm"
            loading={isDiscussing}
            disabled={!starterDraft.trim()}
          >
            Start chat
          </Button>
        </div>
      </form>
    </div>
  );
}
