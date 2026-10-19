import { visibleWidth, wrapTextWithAnsi } from "@earendil-works/pi-tui";
import { type Task, TRANSCRIPT_TAIL_WINDOW } from "@posthog/shared";
import { Box, type DOMElement, Text, useAnimation, useBoxMetrics } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import { type ActionsLine, actionsSheet, openActions } from "../actions";
import { ANIMATION_MS } from "../animation";
import type { Billing } from "../billing";
import { chatgptPlan } from "../chatgpt";
import { type ChatNotice, type ChatView, overlayBottom } from "../chatView";
import { claudePlan } from "../claudeLocal";
import type { Composer } from "../composer";
import { faint } from "../faint";
import type { SearchState } from "../hooks/useSearch";
import type { LocalAgent } from "../local";
import type { Mode } from "../models";
import { type Picker, renderPicker } from "../picker";
import {
  agentUp,
  type CloudRuns,
  deliveryFailure,
  emptyRunView,
  type RunSubscription,
  type RunView,
  runNotice,
  setupProgress,
  windowed,
  withListedRun,
} from "../runs";
import { renderSheet, type Sheet } from "../sheet";
import type { StatusChip } from "../status";
import { orange } from "../theme";
import {
  TODAY_MARGIN,
  type TodayHit,
  type TodayState,
  todayLines,
} from "../today";
import {
  type PendingShell,
  queuedMessage,
  type TranscriptLine,
  transcriptFrom,
  withPending,
  withPendingShells,
} from "../transcript";
import { contextFill, isCompacting, shellsStatus, usageStatus } from "../usage";
import { Search } from "./Search";
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

// Pages a chat shorter than the pane pulls in by itself before it waits for a scroll.
export const FILL_PAGES = 10;

function useRunView(
  runs: CloudRuns | null,
  task: Task | undefined,
  local: LocalAgent | undefined,
): { view: RunView; loadOlder: () => void } {
  const taskId = task?.id;
  const run = task?.latest_run;
  const cloudRunId = run && run.environment !== "local" ? run.id : null;
  // A pi task's runs are one conversation, so its earlier runs page in above the current one.
  const withEarlierRuns = task?.runtime === "pi";
  const [view, setView] = useState(emptyRunView);
  const subscription = useRef<RunSubscription | null>(null);
  // Keyed on ids only: each list refresh brings a new task object for the same run.
  const localWindow = useRef<ReturnType<typeof windowed> | null>(null);
  // How much of the chat the pane shows, so the agent taking over from the saved conversation keeps that depth.
  const shown = useRef({ taskId, count: 0 });
  shown.current = { taskId, count: view.local ? view.entries.length : 0 };
  useEffect(() => {
    const keep = shown.current.taskId === taskId ? shown.current.count : 0;
    setView(emptyRunView);
    if (local) {
      // A local agent keeps its whole log; the pane takes its tail, as it does a cloud run's.
      const window = windowed(setView, {
        tail: Math.max(TRANSCRIPT_TAIL_WINDOW, keep),
      });
      localWindow.current = window;
      const stop = local.watch(window.publish);
      return () => {
        localWindow.current = null;
        stop();
      };
    }
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
  return {
    view,
    loadOlder: () =>
      localWindow.current
        ? localWindow.current.loadOlder()
        : void subscription.current?.loadOlder(),
  };
}

export function Pane({
  title,
  paneTaskId,
  task,
  runs,
  local,
  isLocalPane,
  newChatPlace,
  banner = [],
  billing,
  showContext,
  mode,
  chat,
  composer,
  pending,
  onUndelivered,
  onDelivered,
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
  onModes,
  focused,
  notice: paneNotice,
  reopening,
  repoPicker,
  search = null,
  today = null,
  onTodayHits,
  extraOffer = null,
}: {
  title: string;
  paneTaskId: string | null;
  task: Task | undefined;
  // Null while signed out.
  runs: CloudRuns | null;
  // Set when this pane shows a chat on this machine: its agent, or its saved conversation until the agent starts.
  local: LocalAgent | undefined;
  // True for a chat on this machine, also before its agent has started.
  isLocalPane: boolean;
  // Where a new chat typed here would run.
  newChatPlace: "local" | "cloud";
  // What an empty chat shows above its composer: the model, who pays, and where it runs.
  banner?: string[];
  // Who pays for a new chat, from /billing, until its run says.
  billing?: Billing;
  // The context donut on the composer's rule, from settings.
  showContext?: boolean;
  // The chat's permission mode, shown on the composer's rule beside who pays.
  mode?: string;
  chat: ChatView;
  composer: Composer;
  // A message just sent from this pane that the run has not echoed yet.
  pending: string | null;
  // The backend could not deliver this chat's pending message, logged at `at` (epoch ms).
  onUndelivered: (at: number, sandboxGone: boolean) => void;
  // The chat's log now carries the pending message, so it is no longer on its way.
  onDelivered?: () => void;
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
  // A task search opened in this pane; its pick fills the pane.
  search?: SearchState | null;
  // Called once the chat's run has a live sandbox.
  onRunLive: (taskId: string, runId: string) => void;
  // The run while the agent is mid-turn, or null, so Esc can stop it.
  onTurn: (turn: { taskId: string; runId: string } | null) => void;
  // The modes the chat's session offers and the one it is in, as its log says.
  onModes: (
    taskId: string,
    modes: { available: Mode[]; current: string } | null,
  ) => void;
  focused: boolean;
  // Today's briefing, drawn in place of an empty chat's hint.
  today?: TodayState | null;
  // Where the briefing's links landed, for clicks.
  onTodayHits?: (hits: TodayHit[]) => void;
  // An offer from outside the chat, such as a Today report's questions.
  extraOffer?: ActionsLine | null;
}): ReactElement {
  // A split can hand a pane half a row; the title stays on top and the chat on the bottom, so the spare row falls between them.
  const pane = useRef(null);
  const paneSize = useBoxMetrics(pane);
  const width = Math.max(0, paneSize.width - 2);
  const height = Math.max(0, paneSize.height - 1);
  const { view, loadOlder } = useRunView(runs, task, local);
  const transcript = useMemo(
    () =>
      // A local agent's log holds its first message; a cloud run's omits it, so the task's description stands in.
      task || local
        ? transcriptFrom(
            local?.runtime ?? task?.runtime ?? "pi",
            view.entries,
            task && !local
              ? task.description || task.description_preview
              : undefined,
          )
        : {
            lines: [],
            turnOpen: false,
            lastTurn: null,
            turnStartedAt: null,
            wake: null,
            modes: null,
            shells: 0,
          },
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
    if (delivery && pending) onUndelivered(delivery.at, delivery.sandboxGone);
  }, [delivery?.at, pending]);
  const echoed =
    pending !== null &&
    transcript.lines.findLast((line) => line.kind === "user")?.text === pending;
  // biome-ignore lint/correctness/useExhaustiveDependencies: fires once the chat shows the message
  useEffect(() => {
    if (echoed) onDelivered?.();
  }, [echoed]);
  const setupRunId = task?.latest_run?.id;
  const setup = useMemo(
    () => (setupRunId ? setupProgress(view.entries, setupRunId) : null),
    [view.entries, setupRunId],
  );
  const compacting = useMemo(() => isCompacting(view.entries), [view.entries]);
  // Shells the agent left running after its turn: pi's harness says so in its status line, a Claude Code log by its calls.
  const shellsAfter =
    view.sandboxAlive === false
      ? undefined
      : (shellsStatus(view.entries) ?? transcript.shells);
  // A new chat shows its message and start-up state before the run even exists.
  const notice: ChatNotice | null = task?.latest_run
    ? runNotice(
        withListedRun(view, task.latest_run),
        lines,
        transcript.turnOpen,
        transcript.lastTurn,
        transcript.turnStartedAt,
        {
          setup,
          reopening,
          delivery,
          compacting,
          wake: transcript.wake,
          shells: shellsAfter,
        },
      )
    : local
      ? runNotice(
          view,
          lines,
          transcript.turnOpen,
          transcript.lastTurn,
          transcript.turnStartedAt,
          { compacting, wake: transcript.wake, shells: shellsAfter },
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
  useAnimation({
    interval: ANIMATION_MS,
    isActive: notice?.tone === "working",
  });
  const hasOlder = view.windowStart > 0;
  // Set before this render draws the chat, so a frame never shows the previous transcript.
  const shown = useRef<{
    chat: ChatView;
    lines: typeof lines;
    hasOlder: boolean;
    noticeKey: string;
    queued: boolean;
  } | null>(null);
  const queued = queuedMessage(lines, transcript.turnOpen) !== null;
  if (
    shown.current?.chat !== chat ||
    shown.current.lines !== lines ||
    shown.current.hasOlder !== hasOlder ||
    shown.current.noticeKey !== noticeKey ||
    shown.current.queued !== queued
  ) {
    chat.setTranscript(lines, { hasOlder, notice, queued });
    shown.current = { chat, lines, hasOlder, noticeKey, queued };
  }
  // Scrolling to the top pulls in the page above. A transcript shorter than the pane pulls pages in until it fills,
  // up to FILL_PAGES: a long log of tool noise can show a few lines per page, and paging until it filled once locked the app.
  const pagedAt = useRef<number | null>(null);
  const filled = useRef<{ chat: ChatView; pages: number } | null>(null);
  // A scroll up at the top always asks for the page above, also after the short-transcript page.
  chat.onTopReached = () => {
    if (hasOlder && !view.loadingOlder) loadOlder();
  };
  useEffect(() => {
    if (!(width > 0 && hasOlder && !view.loadingOlder && chat.isAtTop()))
      return;
    if (pagedAt.current === view.windowStart) return;
    if (chat.fitsPane()) {
      const pages = filled.current?.chat === chat ? filled.current.pages : 0;
      if (pages >= FILL_PAGES) return;
      filled.current = { chat, pages: pages + 1 };
    }
    pagedAt.current = view.windowStart;
    loadOlder();
  });
  const run = task?.latest_run;

  // Panes without focus fade back, so the eye lands on the one being typed into.
  const shade = (line: string): string => (focused ? line : faint(line));
  const fill = useMemo(() => contextFill(view.entries), [view.entries]);
  const access = run?.state as
    | { claude_model_access?: string; codex_model_access?: string }
    | undefined;
  // Which of the user's own plans pays for this chat, if any: a local Claude Code chat is the ACP one.
  const onPlan = local
    ? local.plan
      ? local.runtime === "acp"
        ? "claude"
        : "chatgpt"
      : null
    : task
      ? access?.claude_model_access === "own-subscription"
        ? "claude"
        : access?.codex_model_access === "own-subscription"
          ? "chatgpt"
          : null
      : billing === "anthropic"
        ? "claude"
        : billing === "chatgpt"
          ? "chatgpt"
          : null;
  const spent = useTaskCost(
    runs,
    onPlan ? null : paneTaskId,
    transcript.turnOpen,
  );
  const plan = useMemo(
    () => (onPlan === "claude" ? claudePlan() : chatgptPlan()),
    [onPlan],
  );
  const cost = onPlan ? { plan } : spent;
  // A local agent is live once started; a cloud run once its sandbox reports in.
  const live =
    (view.status === "queued" || view.status === "in_progress") &&
    (local ? view.loaded : agentUp(view));
  // A stopped sandbox took its shells with it, whatever its last status said.
  const shells =
    live && view.sandboxAlive !== false
      ? shellsStatus(view.entries)
      : undefined;
  const drawn =
    width > 0
      ? composer.render(
          width,
          focused,
          usageStatus(showContext ? fill : null, cost, shells, mode),
        )
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
    if (paneTaskId) onModes(paneTaskId, transcript.modes);
  });
  const offer = extraOffer ?? openActions(lines);
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
          shade(`${" ".repeat(width - visibleWidth(line))}${orange(line)}`),
        )
      : chat.isScrolledUp()
        ? []
        : [" "];
  const showsComposer =
    !repoPicker && !search && (!modal || Boolean(modal.submitText));
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
  // Drawn from the top and padded to the chat's height, so a click's row is the briefing's row.
  const todayLayout =
    today && !paneTaskId && !pending && width > 0 && chatHeight > 0
      ? todayLines(today, width, new Date().getHours())
      : null;
  useEffect(() => {
    onTodayHits?.(todayLayout?.hits ?? []);
  });
  let content: ReactElement;
  // The briefing's composer starts a chat like an empty pane's, so the same lines say where it would run, under
  // the briefing and in its margin, when the pane has room below it; a popup takes their place.
  const todayFooter =
    popupLines.length > 0
      ? popupLines
      : todayLayout && chatHeight - todayLayout.lines.length > banner.length
        ? banner
            .slice(1)
            .map((line) => faint(`${" ".repeat(TODAY_MARGIN)}${line}`))
        : [];
  if (search) content = <Search search={search} height={chatHeight} />;
  else if (todayLayout)
    content = (
      <Box flexDirection="column">
        {overlayBottom(
          [
            ...todayLayout.lines.slice(0, chatHeight),
            ...Array<string>(
              Math.max(0, chatHeight - todayLayout.lines.length),
            ).fill(""),
          ].map((line) => shade(line || " ")),
          todayFooter,
        ).map((line, index) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: rows are positions on screen
          <Text key={`today-${index}`} wrap="truncate-end">
            {line}
          </Text>
        ))}
      </Box>
    );
  else if (!paneTaskId && !pending)
    content =
      popupLines.length > 0 ? (
        popupContent
      ) : (
        <Box flexDirection="column">
          {banner.map((line, index) => (
            <Text key={line} bold={index === 0} dimColor={index > 0}>
              {line}
            </Text>
          ))}
          <Text> </Text>
          <Text dimColor>
            {newChatPlace === "local"
              ? "Type a message to start a local chat, or press Ctrl+K to find a chat."
              : "Type a message to start a cloud run, or press Ctrl+K to find a chat."}
          </Text>
        </Box>
      );
  else if (isLocalPane && !local && !view.loaded)
    content = (
      <Spinner label={pending ? "Starting local agent…" : "Loading chat"} />
    );
  else if (paneTaskId && !task && !local && !pending)
    content = <Spinner label="Loading chat" />;
  else if (task && !run && !local && !isLocalPane)
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
