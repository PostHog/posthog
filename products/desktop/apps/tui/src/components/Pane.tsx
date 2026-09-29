import type { Task } from "@posthog/shared";
import { Box, type DOMElement, Text, useAnimation, useBoxMetrics } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import { type ActionsLine, actionsSheet, openActions } from "../actions";
import { type ChatView, overlayBottom } from "../chatView";
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
import { renderSheet, type Sheet } from "../sheet";
import type { StatusChip } from "../status";
import { transcriptFrom, withPending } from "../transcript";
import { Spinner } from "./Spinner";

const CHIP_COLORS = {
  open: "green",
  draft: "gray",
  merged: "magenta",
  closed: "red",
} as const;

function useRunView(
  runs: CloudRuns | null,
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
    if (!taskId || !cloudRunId || !runs) return;
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
  modal,
  model,
  chips,
  onPrChip,
  onRunLive,
  focused,
}: {
  title: string;
  paneTaskId: string | null;
  task: Task | undefined;
  // Null while signed out.
  runs: CloudRuns | null;
  chat: ChatView;
  composer: Composer;
  // A message just sent from this pane that the run has not echoed yet.
  pending: string | null;
  onOffer: (offer: ActionsLine | null) => void;
  picker: { index: number; dismissed: Set<string> };
  // A sheet the app opened for this pane, such as the model picker.
  modal: { sheet: Sheet; index: number } | null;
  // The model this chat runs on, when known.
  model: string | undefined;
  // Where the chat runs, its repository and pull request.
  chips: StatusChip[];
  // The pull request chip's box, so a click on it can open the PR.
  onPrChip: (element: DOMElement | null, url: string | null) => void;
  // Called once the chat's run has a live sandbox.
  onRunLive: (taskId: string, runId: string) => void;
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
        : { lines: [], turnOpen: false, lastTurn: null },
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
        transcript.lastTurn,
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
  const drawn =
    width > 0 ? composer.render(width, focused) : { editor: [], popup: [] };
  const composerLines = drawn.editor.map(shade);
  // A blank row on top separates floating suggestions from the chat they cover.
  const popupLines =
    drawn.popup.length > 0 ? [" ", ...drawn.popup.map(shade)] : [];
  const live =
    (view.status === "queued" || view.status === "in_progress") &&
    view.entries.some((entry) => entry.type === "pi_run_started");
  useEffect(() => {
    if (live && task?.latest_run) onRunLive(task.id, task.latest_run.id);
  });
  const offer = openActions(lines);
  useEffect(() => {
    onOffer(offer);
  });
  // A modal sheet takes the composer's place; an offer sheet sits above the composer.
  const offerOpen = offer !== null && !picker.dismissed.has(offer.id);
  const sheetLines =
    width <= 0
      ? []
      : modal
        ? renderSheet(modal.sheet, modal.index, width).map(shade)
        : offerOpen
          ? renderSheet(actionsSheet(offer), picker.index, width).map(shade)
          : [];
  const bottomLines = modal ? sheetLines : [...sheetLines, ...composerLines];
  const chatHeight = height - bottomLines.length - (view.error ? 1 : 0);

  const popupContent = (
    <>
      {popupLines.map((line, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
        <Text key={`popup-${index}`} wrap="truncate-end">
          {line}
        </Text>
      ))}
    </>
  );
  let content: ReactElement;
  if (!paneTaskId && !pending)
    content =
      popupLines.length > 0 ? (
        popupContent
      ) : (
        <Text dimColor>Type a message to start a cloud run.</Text>
      );
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
          ? overlayBottom(chat.render(width, chatHeight).map(shade), popupLines)
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
      <Box justifyContent="space-between" gap={2}>
        <Text bold={focused} dimColor={!focused} wrap="truncate-end">
          {title}
          {model && <Text dimColor> · {model}</Text>}
        </Text>
        <Box flexShrink={0}>
          {chips.map((chip, index) => (
            <Box
              key={chip.label}
              ref={
                chip.url
                  ? (element) => onPrChip(element, chip.url ?? null)
                  : undefined
              }
            >
              <Text
                dimColor={!chip.url || !focused}
                color={chip.tone ? CHIP_COLORS[chip.tone] : undefined}
              >
                {index > 0 ? " · " : ""}
                {chip.url
                  ? `\u001b]8;;${chip.url}\u0007${chip.label}\u001b]8;;\u0007`
                  : chip.label}
              </Text>
            </Box>
          ))}
        </Box>
      </Box>
      <Box height={height} flexDirection="column" overflow="hidden">
        <Box
          flexGrow={1}
          flexDirection="column"
          justifyContent="flex-end"
          overflow="hidden"
        >
          {content}
        </Box>
        {bottomLines.map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
          <Text key={`bottom-${index}`} wrap="truncate-end">
            {line}
          </Text>
        ))}
      </Box>
    </Box>
  );
}
