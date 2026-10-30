import { visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import type { Task } from "@posthog/shared";
import { Box, type DOMElement, Text, useAnimation, useBoxMetrics } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import { type ActionsLine, actionsSheet, openActions } from "../actions";
import { type ChatNotice, type ChatView, overlayBottom } from "../chatView";
import type { Composer } from "../composer";
import { faint } from "../faint";
import type { LocalSession } from "../local";
import { type Picker, renderPicker } from "../picker";
import {
  type CloudRuns,
  deliveryFailure,
  emptyRunView,
  type RunSubscription,
  type RunView,
  runNotice,
  setupProgress,
  withListedRun,
} from "../runs";
import { renderSheet, type Sheet } from "../sheet";
import type { StatusChip } from "../status";
import { blue } from "../theme";
import {
  type PendingShell,
  type TranscriptLine,
  transcriptFrom,
  withPending,
  withPendingShells,
} from "../transcript";
import { contextFill, isCompacting, shellsStatus, usageStatus } from "../usage";
import { Spinner } from "./Spinner";

const COST_REFRESH_MS = 60_000;

// The task's cost, refetched each minute and whenever a turn starts or ends.
function useTaskCost(
  runs: CloudRuns | null,
  taskId: string | null,
  turnOpen: boolean,
): number | null {
  const [cost, setCost] = useState<{ taskId: string; usd: number } | null>(
    null,
  );
  // biome-ignore lint/correctness/useExhaustiveDependencies: turnOpen refetches the cost when a turn starts or ends
  useEffect(() => {
    const fetchCost = runs?.taskCost;
    if (!fetchCost || !taskId) return;
    let stopped = false;
    const load = (): void => {
      // A failed fetch keeps the last figure; the next one may succeed.
      fetchCost(taskId).then(
        (usd) => !stopped && setCost({ taskId, usd }),
        () => {},
      );
    };
    load();
    const timer = setInterval(load, COST_REFRESH_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [runs, taskId, turnOpen]);
  return cost && cost.taskId === taskId ? cost.usd : null;
}

const CHIP_COLORS = {
  open: "green",
  draft: "gray",
  merged: "magenta",
  closed: "red",
} as const;

function useRunView(
  runs: CloudRuns | null,
  task: Task | undefined,
  local: LocalSession | undefined,
): { view: RunView; loadOlder: () => void } {
  const taskId = task?.id;
  const run = task?.latest_run;
  const cloudRunId = run && run.environment !== "local" ? run.id : null;
  // A pi task's runs are one conversation, so its earlier runs page in above the current one.
  const withEarlierRuns = task?.runtime === "pi";
  const [view, setView] = useState(emptyRunView);
  const subscription = useRef<RunSubscription | null>(null);
  // Keyed on ids only: each list refresh brings a new task object for the same run.
  useEffect(() => {
    setView(emptyRunView);
    if (local) return local.watch(setView);
    if (!taskId || !cloudRunId || !runs) return;
    const current = runs.watch(taskId, cloudRunId, setView, {
      withEarlierRuns,
    });
    subscription.current = current;
    return () => {
      subscription.current = null;
      current.stop();
    };
  }, [runs, taskId, cloudRunId, local, withEarlierRuns]);
  return { view, loadOlder: () => void subscription.current?.loadOlder() };
}

export function Pane({
  title,
  paneTaskId,
  task,
  runs,
  local,
  isLocalPane,
  newChatPlace,
  chat,
  composer,
  pending,
  onUndelivered,
  pendingShells,
  onLines,
  onOffer,
  picker,
  modal,
  model,
  chips,
  onPrChip,
  onChatBox,
  onComposerBox,
  onRunLive,
  onTurn,
  focused,
  notice: paneNotice,
  reopening,
  repoPicker,
}: {
  title: string;
  paneTaskId: string | null;
  task: Task | undefined;
  // Null while signed out.
  runs: CloudRuns | null;
  // Set when this pane shows a chat running on this machine.
  local: LocalSession | undefined;
  // True for a chat on this machine, also before its agent has started.
  isLocalPane: boolean;
  // Where a new chat typed here would run.
  newChatPlace: "local" | "cloud";
  chat: ChatView;
  composer: Composer;
  // A message just sent from this pane that the run has not echoed yet.
  pending: string | null;
  // The backend could not deliver this chat's pending message, logged at `at` (epoch ms).
  onUndelivered: (at: number) => void;
  // ! commands run in this chat that its run has not logged yet.
  pendingShells: PendingShell[];
  // The transcript as drawn, so the app can tell a new run of a command from logged ones.
  onLines: (lines: TranscriptLine[]) => void;
  onOffer: (offer: ActionsLine | null) => void;
  picker: { index: number; dismissed: Set<string> };
  // A sheet the app opened for this pane, such as the model picker.
  modal: {
    sheet: Sheet;
    index: number;
    submitText?: (text: string) => void;
  } | null;
  // The model this chat runs on and its effort, when known.
  model: string | undefined;
  // Where the chat runs, its repository and pull request.
  chips: StatusChip[];
  // The pull request chip's box, so a click on it can open the PR.
  onPrChip: (element: DOMElement | null, url: string | null) => void;
  // The chat's box, so a click on a tool group can open it.
  onChatBox: (element: DOMElement | null) => void;
  // The composer's box, from its top rule down, so a click can place the cursor and a drag can select.
  onComposerBox: (element: DOMElement | null) => void;
  // A notice about this chat, shown in a row above the composer.
  notice: string | null;
  // A reply is bringing this chat's stopped run back.
  reopening: boolean;
  // The pane's open /repo picker, drawn in place of the composer.
  repoPicker: Picker | null;
  // Called once the chat's run has a live sandbox.
  onRunLive: (taskId: string, runId: string) => void;
  // The run while the agent is mid-turn, or null, so Esc can stop it.
  onTurn: (turn: { taskId: string; runId: string } | null) => void;
  focused: boolean;
}): ReactElement {
  // A split can hand a pane half a row; the title stays on top and the chat on the bottom, so the spare row falls between them.
  const pane = useRef(null);
  const paneSize = useBoxMetrics(pane);
  const width = Math.max(0, paneSize.width - 2);
  const height = Math.max(0, paneSize.height - 1);
  const { view, loadOlder } = useRunView(runs, task, local);
  const transcript = useMemo(
    () =>
      // A local chat has no server task; its log is pi events.
      task || local
        ? transcriptFrom(
            task?.runtime ?? "pi",
            view.entries,
            task ? task.description || task.description_preview : undefined,
          )
        : { lines: [], turnOpen: false, lastTurn: null, turnStartedAt: null },
    [task, local, view.entries],
  );
  const lines = useMemo(
    () =>
      withPendingShells(withPending(transcript.lines, pending), pendingShells),
    [transcript, pending, pendingShells],
  );
  useEffect(() => {
    onLines(lines);
  });
  const delivery = useMemo(
    () => (local ? null : deliveryFailure(view.entries)),
    [view.entries, local],
  );
  // biome-ignore lint/correctness/useExhaustiveDependencies: fires once per failure, while a message is pending
  useEffect(() => {
    if (delivery && pending) onUndelivered(delivery.at);
  }, [delivery?.at, pending]);
  const setupRunId = task?.latest_run?.id;
  const setup = useMemo(
    () => (setupRunId ? setupProgress(view.entries, setupRunId) : null),
    [view.entries, setupRunId],
  );
  const compacting = useMemo(() => isCompacting(view.entries), [view.entries]);
  // A new chat shows its message and start-up state before the run even exists.
  const notice: ChatNotice | null = task?.latest_run
    ? runNotice(
        withListedRun(view, task.latest_run),
        lines,
        transcript.turnOpen,
        transcript.lastTurn,
        transcript.turnStartedAt,
        { setup, reopening, delivery, compacting },
      )
    : local
      ? runNotice(
          view,
          lines,
          transcript.turnOpen,
          transcript.lastTurn,
          transcript.turnStartedAt,
          { compacting },
        )
      : pending
        ? ({
            text: isLocalPane ? "Starting local agent…" : "Starting cloud run…",
            tone: "working",
          } as const)
        : null;
  const noticeKey = notice
    ? `${notice.tone}:${notice.text}:${notice.detail ?? ""}`
    : "";
  // Keeps a working notice's shimmer moving.
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
  const fill = useMemo(() => contextFill(view.entries), [view.entries]);
  const cost = useTaskCost(runs, paneTaskId, transcript.turnOpen);
  // A local agent is live once started; a cloud run once its sandbox reports in.
  const live =
    (view.status === "queued" || view.status === "in_progress") &&
    (local
      ? view.loaded
      : view.entries.some((entry) => entry.type === "pi_run_started"));
  // A stopped sandbox took its shells with it, whatever its last status said.
  const shells =
    live && view.sandboxAlive !== false
      ? shellsStatus(view.entries)
      : undefined;
  const drawn =
    width > 0
      ? composer.render(width, focused, usageStatus(fill, cost, shells))
      : { editor: [], popup: [] };
  const composerLines = drawn.editor.map(shade);
  // A blank row on top separates floating suggestions from the chat they cover.
  const popupLines =
    drawn.popup.length > 0 ? [" ", ...drawn.popup.map(shade)] : [];
  const runIds = task?.latest_run
    ? { taskId: task.id, runId: task.latest_run.id }
    : local && paneTaskId
      ? { taskId: paneTaskId, runId: "local" }
      : null;
  useEffect(() => {
    if (live && runIds) onRunLive(runIds.taskId, runIds.runId);
    onTurn(live && transcript.turnOpen ? runIds : null);
  });
  const offer = openActions(lines);
  useEffect(() => {
    onOffer(offer);
  });
  // A modal sheet takes the composer's place, unless its answer is typed; an offer sheet sits above the composer.
  const offerOpen = offer !== null && !picker.dismissed.has(offer.id);
  const sheetLines =
    width <= 0
      ? []
      : repoPicker
        ? renderPicker(repoPicker, width).map(shade)
        : modal
          ? renderSheet(modal.sheet, modal.index, width).map(shade)
          : offerOpen
            ? renderSheet(actionsSheet(offer), picker.index, width).map(shade)
            : [];
  // The row stays when empty, so a notice never moves the chat. It ends flush right, like the usage on the rule below.
  // A chat scrolled up does not follow the end, so it takes the empty row without moving, for its jump-back pill.
  const noticeLines =
    paneNotice && width > 1
      ? wrapTextWithAnsi(paneNotice, width - 1).map((line) =>
          shade(`${" ".repeat(width - visibleWidth(line))}${blue(line)}`),
        )
      : chat.isScrolledUp()
        ? []
        : [" "];
  const showsComposer = !repoPicker && (!modal || Boolean(modal.submitText));
  const bottomLines = [
    ...noticeLines,
    ...sheetLines,
    ...(showsComposer ? composerLines : []),
  ];
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
        <Text dimColor>
          {newChatPlace === "local"
            ? `Type a message to start a local chat in ${process.cwd()}, or press Ctrl+K to find a chat.`
            : "Type a message to start a cloud run, or press Ctrl+K to find a chat."}
        </Text>
      );
  else if (isLocalPane && !local)
    content = <Spinner label="Starting local agent…" />;
  else if (paneTaskId && !task && !local && !pending)
    content = <Spinner label="Loading chat" />;
  else if (task && !run && !local)
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
          ref={onChatBox}
          flexGrow={1}
          flexDirection="column"
          justifyContent="flex-end"
          overflow="hidden"
        >
          {content}
        </Box>
        {noticeLines.map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
          <Text key={`notice-${index}`} wrap="truncate-end">
            {line}
          </Text>
        ))}
        {sheetLines.map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
          <Text key={`sheet-${index}`} wrap="truncate-end">
            {line}
          </Text>
        ))}
        {showsComposer && (
          <Box ref={onComposerBox} flexDirection="column" flexShrink={0}>
            {composerLines.map((line, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
              <Text key={`composer-${index}`} wrap="truncate-end">
                {line}
              </Text>
            ))}
          </Box>
        )}
      </Box>
    </Box>
  );
}
