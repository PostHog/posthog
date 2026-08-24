import { ChatCircleIcon, XIcon } from "@phosphor-icons/react";
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
  findLatestDiscussionTask,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
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
 * report they were asking about). One persistent discussion per report:
 * opening the panel resumes the report's existing discussion task, and only
 * the first question creates one.
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
  // discussion started seconds ago is bridged by the store until it does.
  const { data: reportTasks, isLoading: isLoadingTasks } = useReportTasks(
    report.id,
    report.status,
  );
  const discussionTask = findLatestDiscussionTask(reportTasks);
  const taskId = discussionTask?.id ?? startedTaskId;

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
          <span className="flex items-center gap-1.5 font-medium text-[13px] text-gray-12">
            <ChatCircleIcon size={14} />
            Chat
          </span>
          <Button
            size="icon-sm"
            variant="default"
            aria-label="Close chat"
            onClick={() => setOpen(false)}
          >
            <XIcon size={14} />
          </Button>
        </div>
        <div className="min-h-0 flex-1">
          {taskId ? (
            <ReportChatConversation reportId={report.id} taskId={taskId} />
          ) : isLoadingTasks ? (
            // Until the report's tasks load we can't tell whether a discussion
            // already exists; showing the starter here would let a fast submit
            // open a second discussion for a report that already has one.
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
  reportId,
  taskId,
}: {
  reportId: string;
  taskId: string;
}) {
  const { data: task } = useQuery(taskDetailQuery(taskId));

  const pendingQuote = useReportChatPanelStore(
    (s) => s.pendingQuoteByReport[reportId] ?? null,
  );
  const clearPendingQuote = useReportChatPanelStore((s) => s.clearPendingQuote);
  const { insertPendingContent, getDraft, requestFocus } = useDraftStore(
    (s) => s.actions,
  );

  // A highlighted passage is appended into the session composer, after anything
  // already typed rather than replacing it. Inserting (rather than rewriting the
  // draft) keeps chips and file attachments the user already added, and reaches
  // the live editor even when it already holds text.
  useEffect(() => {
    if (!pendingQuote || !task) return;
    const separator = isContentEmpty(getDraft(taskId)) ? "" : "\n\n";
    insertPendingContent(taskId, textToContent(`${separator}${pendingQuote}`));
    clearPendingQuote(reportId);
    requestFocus(taskId);
  }, [
    pendingQuote,
    task,
    taskId,
    reportId,
    getDraft,
    insertPendingContent,
    clearPendingQuote,
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
  const clearPendingQuote = useReportChatPanelStore((s) => s.clearPendingQuote);
  const starterDraft = useReportChatPanelStore(
    (s) => s.starterDraftByReport[report.id] ?? "",
  );
  const setStarterDraft = useReportChatPanelStore((s) => s.setStarterDraft);
  const clearStarterDraft = useReportChatPanelStore((s) => s.clearStarterDraft);

  // Taken atomically so a double-fired effect can't paste the quote twice.
  useEffect(() => {
    if (!pendingQuote) return;
    const current =
      useReportChatPanelStore.getState().starterDraftByReport[report.id] ?? "";
    setStarterDraft(
      report.id,
      current.trim() ? `${current.trimEnd()}\n\n${pendingQuote}` : pendingQuote,
    );
    clearPendingQuote(report.id);
  }, [pendingQuote, clearPendingQuote, setStarterDraft, report.id]);

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

  // Canned starter prompts go through the same privacy-safe path as submit:
  // the analytics event records that a question was asked, never its text.
  const ask = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isDiscussing) return;
      fireAction("discuss", { has_question: true });
      void discussReport(trimmed);
    },
    [isDiscussing, discussReport, fireAction],
  );

  return (
    <div className="flex h-full flex-col justify-between gap-3 p-3">
      <div className="flex flex-col gap-1 pt-1">
        <span className="font-medium text-[13px] text-gray-12">
          Chat about this report
        </span>
        <span className="text-[12px] text-gray-11">
          The agent joins with the full report and its evidence already in
          context. Highlight any part of the report to quote it here.
        </span>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {[
            "What caused this?",
            "Who is affected?",
            "Walk me through the fix",
          ].map((prompt) => (
            <Button
              key={prompt}
              type="button"
              variant="outline"
              size="sm"
              // Once the composer holds a typed draft or a quoted passage, the
              // one-click chips step aside — firing a chip must not silently
              // discard what the user wrote or highlighted.
              disabled={isDiscussing || starterDraft.trim().length > 0}
              onClick={() => ask(prompt)}
            >
              {prompt}
            </Button>
          ))}
        </div>
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
          <span className="text-[11px] text-gray-10">
            {isMac ? "⌘↵" : "Ctrl+↵"} to send
          </span>
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={!starterDraft.trim() || isDiscussing}
          >
            {isDiscussing && <Spinner />}
            Start chat
          </Button>
        </div>
      </form>
    </div>
  );
}
