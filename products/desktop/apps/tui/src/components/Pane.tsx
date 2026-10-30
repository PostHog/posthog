import type { Task } from "@posthog/shared";
import { Box, Text, useAnimation, useBoxMetrics } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import { type ActionsLine, canRun, openActions } from "../actions";
import type { ChatView } from "../chatView";
import type { Composer } from "../composer";
import { faint } from "../faint";
import {
  type CloudRuns,
  emptyRunView,
  type RunSubscription,
  type RunView,
  runNotice,
  withListedRun,
} from "../runs";
import { transcriptFrom, withPending } from "../transcript";
import { Spinner } from "./Spinner";

function useRunView(
  runs: CloudRuns,
  task: Task | undefined,
): { view: RunView; loadOlder: () => void } {
  const taskId = task?.id;
  const run = task?.latest_run;
  const cloudRunId = run && run.environment !== "local" ? run.id : null;
  const [view, setView] = useState(emptyRunView);
  const subscription = useRef<RunSubscription | null>(null);
  // Keyed on ids only: each list refresh brings a new task object for the same run.
  useEffect(() => {
    setView(emptyRunView);
    if (!taskId || !cloudRunId) return;
    const current = runs.watch(taskId, cloudRunId, setView);
    subscription.current = current;
    return () => {
      subscription.current = null;
      current.stop();
    };
  }, [runs, taskId, cloudRunId]);
  return { view, loadOlder: () => void subscription.current?.loadOlder() };
}

export function Pane({
  title,
  paneTaskId,
  task,
  runs,
  chat,
  composer,
  pending,
  onOffer,
  picker,
  focused,
}: {
  title: string;
  paneTaskId: string | null;
  task: Task | undefined;
  runs: CloudRuns;
  chat: ChatView;
  composer: Composer;
  // A message just sent from this pane that the run has not echoed yet.
  pending: string | null;
  onOffer: (offer: ActionsLine | null) => void;
  picker: { index: number; dismissed: Set<string> };
  focused: boolean;
}): ReactElement {
  // A split can hand a pane half a row; the title stays on top and the chat on the bottom, so the spare row falls between them.
  const pane = useRef(null);
  const paneSize = useBoxMetrics(pane);
  const width = Math.max(0, paneSize.width - 2);
  const height = Math.max(0, paneSize.height - 1);
  const { view, loadOlder } = useRunView(runs, task);
  const transcript = useMemo(
    () =>
      task
        ? transcriptFrom(
            task.runtime,
            view.entries,
            task.description || task.description_preview,
          )
        : { lines: [], turnOpen: false },
    [task, view.entries],
  );
  const lines = useMemo(
    () => withPending(transcript.lines, pending),
    [transcript, pending],
  );
  // A new chat shows its message and start-up state before the run even exists.
  const notice = task?.latest_run
    ? runNotice(
        withListedRun(view, task.latest_run),
        lines,
        transcript.turnOpen,
      )
    : pending
      ? ({ text: "Starting cloud run…", tone: "working" } as const)
      : null;
  const noticeKey = notice ? `${notice.tone}:${notice.text}` : "";
  // Keeps a working notice's spinner turning.
  useAnimation({ interval: 80, isActive: notice?.tone === "working" });
  const hasOlder = view.windowStart > 0;
  // Set before this render draws the chat, so a frame never shows the previous transcript.
  const shown = useRef<{
    chat: ChatView;
    lines: typeof lines;
    hasOlder: boolean;
    noticeKey: string;
  } | null>(null);
  if (
    shown.current?.chat !== chat ||
    shown.current.lines !== lines ||
    shown.current.hasOlder !== hasOlder ||
    shown.current.noticeKey !== noticeKey
  ) {
    chat.setTranscript(lines, { hasOlder, notice });
    shown.current = { chat, lines, hasOlder, noticeKey };
  }
  // Reaching the top, or a transcript shorter than the pane, pulls in the page above.
  useEffect(() => {
    if (width > 0 && hasOlder && !view.loadingOlder && chat.isAtTop())
      loadOlder();
  });
  const run = task?.latest_run;

  // Panes without focus fade back, so the eye lands on the one being typed into.
  const shade = (line: string): string => (focused ? line : faint(line));
  const composerLines =
    width > 0 ? composer.render(width, focused).map(shade) : [];
  const offer = openActions(lines);
  useEffect(() => {
    onOffer(offer);
  });
  const pickerOpen = offer !== null && !picker.dismissed.has(offer.id);
  const pickerRows = pickerOpen ? offer.actions.length + 1 : 0;
  const chatHeight =
    height - composerLines.length - pickerRows - (view.error ? 1 : 0);

  let content: ReactElement;
  if (!paneTaskId && !pending)
    content = <Text dimColor>Type a message to start a cloud run.</Text>;
  else if (paneTaskId && !task && !pending)
    content = <Spinner label="Loading chat" />;
  else if (task && !run)
    content = <Text dimColor>This task has no runs yet.</Text>;
  else if (run?.environment === "local")
    content = <Text dimColor>Local runs can't be opened here yet.</Text>;
  else if (!view.loaded && !view.error && lines.length === 0)
    content = <Spinner label="Loading chat" />;
  else {
    // pi renders at the pane's measured size; each line is already styled and fitted to the width.
    content = (
      <>
        {(width > 0 && chatHeight > 0
          ? chat.render(width, chatHeight).map(shade)
          : []
        ).map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
          <Text key={index} wrap="truncate-end">
            {line}
          </Text>
        ))}
        {view.error && <Text color="red">{view.error}</Text>}
      </>
    );
  }

  return (
    <Box
      ref={pane}
      flexGrow={1}
      flexDirection="column"
      justifyContent="space-between"
      paddingX={1}
      overflow="hidden"
    >
      <Text bold={focused} dimColor={!focused} wrap="truncate-end">
        {title}
      </Text>
      <Box height={height} flexDirection="column" overflow="hidden">
        <Box
          flexGrow={1}
          flexDirection="column"
          justifyContent="flex-end"
          overflow="hidden"
        >
          {content}
        </Box>
        {pickerOpen &&
          offer.actions.map((action, index) => {
            const selected = focused && index === picker.index;
            return (
              <Text
                key={`${offer.id}:${action.label}`}
                wrap="truncate-end"
                dimColor={!focused || !canRun(action)}
              >
                {selected ? "› " : "  "}
                <Text inverse={selected}>{action.label}</Text>
                {!canRun(action) && " (PostHog Desktop only)"}
              </Text>
            );
          })}
        {pickerOpen && (
          <Text dimColor wrap="truncate-end">
            ↑↓ choose · Enter open · Esc dismiss
          </Text>
        )}
        {composerLines.map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
          <Text key={`composer-${index}`} wrap="truncate-end">
            {line}
          </Text>
        ))}
      </Box>
    </Box>
  );
}
