import type { CloudRegion, Task } from "@posthog/shared";
import { Box, type DOMElement, useBoxMetrics } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import type { ActionsLine } from "../actions";
import { currentRepository, type PiChats } from "../chats";
import { dividerGlyphs } from "../dividers";
import { useChatPlace } from "../hooks/useChatPlace";
import { useKeys } from "../hooks/useKeys";
import { useLocalChats } from "../hooks/useLocalChats";
import { useModels } from "../hooks/useModels";
import { noticeIn, useNotice } from "../hooks/useNotice";
import { usePaneViews } from "../hooks/usePaneViews";
import { usePointer } from "../hooks/usePointer";
import { useRepoPicker } from "../hooks/useRepoPicker";
import { useSearch } from "../hooks/useSearch";
import { type Send, useSend } from "../hooks/useSend";
import { useSettings } from "../hooks/useSettings";
import { useSheets } from "../hooks/useSheets";
import { useShell } from "../hooks/useShell";
import { useSidebar } from "../hooks/useSidebar";
import { useTerminalInput } from "../hooks/useTerminalInput";
import { useToday } from "../hooks/useToday";
import { useTurns } from "../hooks/useTurns";
import { useWorkList } from "../hooks/useWorkList";
import {
  activeWorkspace,
  adoptSharedLayout,
  allPanes,
  findPane,
  type LayoutState,
  layoutPath,
  loadLayout,
  type PaneNode,
  paneIds,
  panes,
  saveLayout,
} from "../layout";
import type { LocalSession } from "../local";
import type { PiControl } from "../models";
import type { MouseEvents } from "../mouse";
import { openUrl } from "../openUrl";
import { loadPrefs, savePrefs } from "../prefs";
import type { CloudRuns } from "../runs";
import { repoLabel, statusChips } from "../status";
import { applyBackground, backgroundFromReply } from "../theme";
import {
  reportPrompt,
  type TodayAction,
  type TodayClient,
  type TodayHit,
  todayHitAt,
  WALKTHROUGH_PROMPT,
} from "../today";
import type { WorkList } from "../work";
import { Pane } from "./Pane";
import { DividerColumn, PaneTree } from "./PaneTree";
import { Search } from "./Search";
import { Settings } from "./Settings";
import { Sidebar } from "./Sidebar";

export interface Session {
  account?: string;
  work: WorkList;
  runs: CloudRuns;
  chats: PiChats;
  control: (taskId: string, runId: string) => PiControl;
  startLocal: (id: string) => Promise<LocalSession>;
  // Today's briefing; absent in tests that do not need it.
  today?: TodayClient;
}

export function App({
  session,
  login,
  logout,
  mouse,
}: {
  // Null while signed out: the layout and composers still work, and /login signs in.
  session: Session | null;
  login: (region: CloudRegion, onAuth: (url: string) => void) => Promise<void>;
  logout: () => void;
  mouse?: MouseEvents;
}): ReactElement {
  const {
    work,
    runs,
    chats,
    control: cloudControl,
    startLocal,
  } = session ?? {};
  const notice = useNotice();
  const { flashNotice } = notice;
  const layoutFile = layoutPath(session?.account);
  const [layout, setLayout] = useState<LayoutState>(() => {
    adoptSharedLayout(layoutFile);
    return loadLayout(layoutFile);
  });
  const layoutFrom = useRef(layoutFile);
  // Tasks this app just started or resumed; they win until the list shows the same run.
  const [fresh, setFresh] = useState<Map<string, Task>>(new Map());
  const [narrowSidebar, setNarrowSidebar] = useState(
    () => loadPrefs().narrowSidebar,
  );
  // Bumped when the terminal turns light or dark, so everything draws again in its colours.
  const [, setThemeVersion] = useState(0);
  // Names given with /rename, shown at once and kept until the work list shows them too.
  const [titles, setTitles] = useState<Map<string, string>>(new Map());
  const {
    isLocal,
    localFor,
    localSessions,
    clear: clearLocal,
    localActive,
    markActive,
    refreshActive: refreshLocalActive,
    prompts,
    promptCursors,
    setPromptCursor,
  } = useLocalChats({
    startLocal,
    chats,
    layout,
    setLayout,
    setFresh,
    flashNotice,
  });
  // Cloud runs go through the engine; local chats through their own agent process.
  const control = cloudControl
    ? (taskId: string, runId: string): PiControl =>
        isLocal(taskId)
          ? (localSessions.get(taskId)?.control ?? cloudControl(taskId, runId))
          : cloudControl(taskId, runId)
    : undefined;
  const { placeFor, setPlace } = useChatPlace();
  // Repaints are not needed elsewhere: setting state draws the new colours, and chats drop their cached lines.
  const onBackground = useRef((_reply: string): void => {});
  useEffect(() => {
    if (!mouse) return;
    const listener = (reply: string): void => onBackground.current(reply);
    mouse.on("background", listener);
    return () => {
      mouse.off("background", listener);
    };
  }, [mouse]);
  const newChatRepository = useMemo(() => currentRepository(), []);
  const chatArea = useRef<DOMElement | null>(null);
  const area = useBoxMetrics(chatArea);
  // Composers outlive renders, so they submit through the latest onSubmit.
  const latestSubmit = useRef<Send["onSubmit"]>(() => {});
  const {
    chatFor,
    chatIn,
    chats: allChats,
    composerFor,
    scrollPane,
    linesOf,
    setLines,
    repaint,
  } = usePaneViews({
    layout,
    onSubmit: (paneId, text, images) =>
      latestSubmit.current(paneId, text, images),
  });

  // A sign-in or sign-out swaps in that account's layout before anything is saved to its file.
  useEffect(() => {
    if (layoutFrom.current !== layoutFile) {
      layoutFrom.current = layoutFile;
      adoptSharedLayout(layoutFile);
      setLayout(loadLayout(layoutFile));
    } else saveLayout(layout, layoutFile);
  }, [layout, layoutFile]);

  const {
    page,
    known,
    taskOf,
    loadMore,
    reset: resetWork,
  } = useWorkList({
    work,
    runs,
    fresh,
    openTaskIds: [
      ...allPanes(layout).flatMap((pane) => (pane.taskId ? [pane.taskId] : [])),
      ...localActive.keys(),
    ],
    onRefresh: refreshLocalActive,
  });

  const turns = useTurns({
    layout,
    runs: runs ?? null,
    taskOf,
    localSessions,
  });
  const search = useSearch({
    work,
    recent: page.tasks,
    setLayout,
    working: turns.working,
    waiting: turns.waiting,
    local: { active: localActive, running: new Set(localSessions.keys()) },
  });

  const settings = useSettings();

  const { modalFor, openModal, onModalKey } = useSheets({
    layout,
    prompts,
    promptCursors,
    setPromptCursor,
    localSessions,
    composerFor,
    flashNotice,
  });

  const {
    openModelSheet,
    openEffortSheet,
    compact,
    onRunLive,
    onChatStarted,
    modelLabel,
  } = useModels({
    layout,
    isLocal,
    localSessions,
    control,
    composerFor,
    openModal,
    notice,
  });

  const { runShell, shellsFor } = useShell({
    taskOf,
    isLocal,
    localFor,
    control,
    composerFor,
    linesOf,
    flashNotice,
  });

  const repoPicker = useRepoPicker({
    search: chats ? (query) => chats.searchRepositories(query) : null,
    defaultRepo: newChatRepository,
    flashNotice,
  });

  const { onSubmit, pending, reopening, undelivered } = useSend({
    layout,
    setLayout,
    setFresh,
    chats,
    taskOf,
    resetWork,
    local: { isLocal, localFor, clear: clearLocal, markActive },
    places: { placeFor, setPlace },
    composerFor,
    modalFor,
    openModal,
    openModelSheet,
    openEffortSheet,
    compact,
    openSearch: search.toggle,
    openSettings: settings.toggle,
    repos: repoPicker,
    onChatStarted,
    setTitles,
    runShell,
    notice,
    login,
    logout,
  });

  const sidebar = useSidebar({
    layout,
    setLayout,
    page,
    known,
    fresh,
    signedIn: session !== null,
    localActive,
    localSessions,
    loadMore,
    working: turns.working,
    waiting: turns.waiting,
    titles,
  });
  const caughtUp = [...titles].filter(
    ([taskId, title]) => taskOf(taskId)?.title === title,
  );
  useEffect(() => {
    if (caughtUp.length === 0) return;
    setTitles((current) => {
      const next = new Map(current);
      for (const [taskId, title] of caughtUp)
        if (next.get(taskId) === title) next.delete(taskId);
      return next;
    });
  });
  const workspace = activeWorkspace(layout);
  const sidebarFocused = layout.focus === "sidebar";

  // A pane with no chat yet runs where its place says.
  const runsLocally = (paneId: string, taskId: string | null): boolean =>
    isLocal(taskId) || (!taskId && placeFor(paneId) === "local");

  // The main view shows today's briefing while it has no chat and no message on its way.
  const mainView = layout.workspaces.find(
    (candidate) => panes(candidate.root).length === 1,
  );
  const mainPane = mainView ? panes(mainView.root)[0] : undefined;
  // Without a briefing to read, such as when signed out, the main view stays a plain new chat.
  const todayPaneId =
    session?.today &&
    mainPane &&
    mainPane.taskId === null &&
    !pending.has(mainPane.id)
      ? mainPane.id
      : null;
  const todayState = useToday(
    session?.today,
    todayPaneId !== null && workspace.id === mainView?.id,
  );
  const todayHits = useRef<TodayHit[]>([]);
  const [todayOffer, setTodayOffer] = useState<ActionsLine | null>(null);
  const onTodayAction = (paneId: string, action: TodayAction): void => {
    const today = session?.today;
    if (!today) return;
    if (action.kind === "ask") latestSubmit.current(paneId, WALKTHROUGH_PROMPT);
    else if (action.kind === "inbox") void today.inboxUrl().then(openUrl);
    else {
      const { item } = action;
      void today.questions(item).then((questions) =>
        setTodayOffer({
          kind: "actions",
          id: `today:${item.key}:${Date.now()}`,
          title: item.label,
          actions: questions.map((question) => ({
            kind: "compose",
            label: question,
            prompt: reportPrompt(question, item, today.webUrl(item.url)),
          })),
        }),
      );
    }
  };

  const { boxes, paneAtDrop, ...pointer } = usePointer({
    rows: sidebar.rows,
    activate: sidebar.activate,
    setNavigating: sidebar.setNavigating,
    setLayout,
    chatIn,
    chats: allChats,
    composerFor,
    scrollPane,
    repaint,
    flashNotice,
    todayAt: (paneId, row, column) => {
      if (paneId !== todayPaneId) return false;
      const action = todayHitAt(todayHits.current, row, column);
      if (action) onTodayAction(paneId, action);
      return action !== null;
    },
  });

  const { onKey, setOffer, setTurn, pickerFor } = useKeys({
    layout,
    setLayout,
    sidebar,
    search,
    settings,
    composerFor,
    modalFor,
    onModalKey,
    scrollPane,
    control,
    paneAtDrop,
    toggleSidebar: () => {
      setNarrowSidebar(!narrowSidebar);
      savePrefs({ narrowSidebar: !narrowSidebar });
    },
    repoPickerKey: repoPicker.onKey,
    notice,
  });
  useTerminalInput(mouse, { ...pointer, onKey });
  latestSubmit.current = onSubmit;

  onBackground.current = (reply) => {
    const background = backgroundFromReply(reply);
    if (!background) return;
    applyBackground(background);
    for (const chat of allChats()) chat.invalidate();
    setThemeVersion((version) => version + 1);
  };

  const titleOf = (pane: PaneNode): string => {
    if (pane.taskId === null)
      return pane.id === todayPaneId ? "Today" : "New chat";
    return (
      titles.get(pane.taskId) ||
      taskOf(pane.taskId)?.title ||
      pane.title ||
      "Untitled"
    );
  };

  const renderPane = (node: PaneNode): ReactElement => (
    <Pane
      title={titleOf(node)}
      paneTaskId={node.taskId}
      task={taskOf(node.taskId)}
      runs={runs ?? null}
      local={isLocal(node.taskId) ? localSessions.get(node.taskId) : undefined}
      isLocalPane={runsLocally(node.id, node.taskId)}
      newChatPlace={placeFor(node.id)}
      chat={chatFor(node.id, node.taskId)}
      composer={composerFor(node.id)}
      pending={pending.get(node.taskId ?? node.id) ?? null}
      reopening={node.taskId ? reopening.has(node.taskId) : false}
      today={node.id === todayPaneId ? todayState : null}
      onTodayHits={(hits) => {
        if (node.id === todayPaneId) todayHits.current = hits;
      }}
      extraOffer={node.id === todayPaneId ? todayOffer : null}
      repoPicker={repoPicker.pickerFor(node.id) ?? null}
      onUndelivered={(at) =>
        node.taskId && undelivered(node.id, node.taskId, at)
      }
      pendingShells={shellsFor(node.taskId)}
      onLines={(lines) => setLines(node.id, lines)}
      onOffer={(offer) => setOffer(node.id, offer)}
      picker={pickerFor(node.id)}
      modal={modalFor(node.id) ?? null}
      model={modelLabel(node.id, node.taskId)}
      onRunLive={(taskId, runId) => onRunLive(node.id, taskId, runId)}
      onTurn={(turn) => setTurn(node.id, turn)}
      chips={
        isLocal(node.taskId) || !node.taskId
          ? statusChips(
              undefined,
              isLocal(node.taskId) || placeFor(node.id) === "local"
                ? newChatRepository
                : repoLabel(repoPicker.reposFor(node.id)),
              isLocal(node.taskId) ? "local" : placeFor(node.id),
            )
          : taskOf(node.taskId)
            ? statusChips(taskOf(node.taskId), newChatRepository)
            : []
      }
      onPrChip={(element, url) => boxes.setPrChip(node.id, element, url)}
      onChatBox={(element) => boxes.setChat(node.id, element)}
      onComposerBox={(element) => boxes.setComposer(node.id, element)}
      focused={!sidebarFocused && node.id === workspace.focusedPaneId}
      notice={
        noticeIn(notice.shown, node.id, node.taskId) && notice.shown
          ? notice.shown.text
          : null
      }
    />
  );

  if (search.open) return <Search search={search} />;
  if (settings.open) return <Settings settings={settings} />;

  // A chat's notice falls back to the sidebar while no pane on screen shows the chat.
  const sidebarNotice =
    notice.shown &&
    !paneIds(workspace.root).some((paneId) =>
      noticeIn(notice.shown, paneId, findPane(layout, paneId)?.taskId ?? null),
    )
      ? notice.shown.text
      : null;

  const glyph = dividerGlyphs(workspace.root, area.width, area.height);

  // A spare row under everything keeps bottom composers off the window's edge.
  return (
    <Box flexGrow={1} paddingBottom={1}>
      <Sidebar
        boxRef={boxes.sidebar}
        notice={sidebarNotice}
        rows={sidebar.rows}
        focused={sidebarFocused}
        selectedIndex={sidebar.selectedIndex}
        activePaneId={workspace.focusedPaneId}
        narrow={narrowSidebar}
      />
      {area.hasMeasured && (
        <DividerColumn x={-1} y={0} height={area.height} glyph={glyph} />
      )}
      <Box ref={chatArea} flexGrow={1}>
        {area.hasMeasured && (
          <PaneTree
            cell={{
              node: workspace.root,
              divider: null,
              x: 0,
              y: 0,
              width: area.width,
              height: area.height,
            }}
            glyph={glyph}
            renderPane={renderPane}
            onPaneBox={boxes.setPane}
          />
        )}
      </Box>
    </Box>
  );
}
