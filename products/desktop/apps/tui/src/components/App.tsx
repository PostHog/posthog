import { homedir } from "node:os";
import type { CloudRegion, Task } from "@posthog/shared";
import { Box, type DOMElement, useApp, useBoxMetrics } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import type { ActionsLine } from "../actions";
import { track } from "../analytics";
import { bannerLines } from "../banner";
import type { StartPick } from "../chats";
import { currentRepository, type PiChats } from "../chats";
import { runClaudeSetupToken } from "../claudeSetup";
import { dividerGlyphs } from "../dividers";
import { useAccount } from "../hooks/useAccount";
import { useChatPlace } from "../hooks/useChatPlace";
import { useHistory } from "../hooks/useHistory";
import { useKeys } from "../hooks/useKeys";
import { useLocalChats } from "../hooks/useLocalChats";
import { useMcpSheet } from "../hooks/useMcpSheet";
import { useModels } from "../hooks/useModels";
import { noticeIn, useNotice } from "../hooks/useNotice";
import { usePaneViews } from "../hooks/usePaneViews";
import { usePointer } from "../hooks/usePointer";
import { useRepoPicker } from "../hooks/useRepoPicker";
import { type SearchState, useSearch } from "../hooks/useSearch";
import { type Send, useSend } from "../hooks/useSend";
import type { CodexCloudClient } from "../hooks/useSettings";
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
import type { LocalAgent } from "../local";
import type { McpClient } from "../mcp";
import { type PiControl, runModel } from "../models";
import type { MouseEvents } from "../mouse";
import { openUrl } from "../openUrl";
import { type ChatScope, loadPrefs, savePrefs } from "../prefs";
import type { AgentPrompt } from "../prompts";
import type { CloudRuns } from "../runs";
import { startingOptions } from "../starting";
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
import { Help } from "./Help";
import { Pane } from "./Pane";
import { DividerColumn, PaneTree } from "./PaneTree";
import { Search } from "./Search";
import { Settings } from "./Settings";
import { CHROME_ROWS, Sidebar } from "./Sidebar";
import { Welcome } from "./Welcome";

export interface Session {
  account?: string;
  work: WorkList;
  runs: CloudRuns;
  chats: PiChats;
  control: (taskId: string, runId: string) => PiControl;
  startLocal: (id: string, pick?: StartPick) => Promise<LocalAgent>;
  // Today's briefing; absent in tests that do not need it.
  today?: TodayClient;
  // The ChatGPT account PostHog holds for cloud Codex runs; absent in tests that do not need it.
  codexCloud?: CodexCloudClient;
  // The account's MCP servers; absent in tests that do not need it.
  mcp?: McpClient;
}

// Hands the terminal's input to `run` and takes it back after, around Ink's own suspension.
export type Handoff = (run: () => Promise<void>) => Promise<void>;

export function App({
  session,
  login,
  logout,
  mouse,
  handoff,
}: {
  // Null while signed out: the layout and composers still work, and /login signs in.
  session: Session | null;
  login: (region: CloudRegion, onAuth: (url: string) => void) => Promise<void>;
  logout: () => void;
  mouse?: MouseEvents;
  // Absent where no terminal can be handed over, such as tests.
  handoff?: Handoff;
}): ReactElement {
  const {
    work,
    runs,
    chats,
    control: cloudControl,
    startLocal,
  } = session ?? {};
  const notice = useNotice();
  const { suspendTerminal } = useApp();
  // Runs `claude setup-token` on the user's terminal and returns the token it prints.
  const runSetup = handoff
    ? async (): Promise<string> => {
        let token = "";
        await handoff(() =>
          suspendTerminal(async () => {
            token = await runClaudeSetupToken();
          }),
        );
        return token;
      }
    : undefined;
  const { flashNotice } = notice;
  const layoutFile = layoutPath(session?.account);
  const [layout, setLayout] = useState<LayoutState>(() => {
    adoptSharedLayout(layoutFile);
    return loadLayout(layoutFile);
  });
  const layoutFrom = useRef(layoutFile);
  useEffect(() => {
    if (session?.account) track("signed in");
  }, [session?.account]);
  // Tasks this app just started or resumed; they win until the list shows the same run.
  const [fresh, setFresh] = useState<Map<string, Task>>(new Map());
  const [narrowSidebar, setNarrowSidebar] = useState(
    () => loadPrefs().narrowSidebar,
  );
  const [pinned, setPinned] = useState(() => loadPrefs().pinnedChats);
  const [scope, setScope] = useState(() => loadPrefs().chatScope);
  const switchScope = (next: ChatScope): void => {
    if (next === scope) return;
    track("chat scope switched", { scope: next });
    setScope(next);
    savePrefs({ chatScope: next });
  };
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
    coldSessions,
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
  // What each pane and the model picker see of a local chat: its running agent, or its saved conversation.
  const shownSessions = useMemo(
    () => new Map([...coldSessions, ...localSessions]),
    [coldSessions, localSessions],
  );
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
      ...pinned.map((chat) => chat.id),
    ],
    onRefresh: refreshLocalActive,
    scope,
  });

  // The search opens from a callback only, so the send hook reaches it through a ref: the search needs the turns,
  // and the turns need the send hook's pending messages.
  const latestSearch = useRef<SearchState | null>(null);

  // Today's briefing can be hidden from settings; the sidebar and the main view follow the switch at once.
  const [showToday, setShowToday] = useState(() => loadPrefs().showToday);
  const settings = useSettings(session?.codexCloud, runSetup, setShowToday);
  const [helpOpen, setHelpOpen] = useState(false);

  // A cloud run's own prompts, from the engine; a local chat's come from its agent.
  const [cloudPrompts, setCloudPrompts] = useState<Map<string, AgentPrompt[]>>(
    new Map(),
  );
  useEffect(() => runs?.watchPrompts(setCloudPrompts), [runs]);
  const { modalFor, openModal, closeModal, onModalKey } = useSheets({
    layout,
    prompts: useMemo(
      () => new Map([...cloudPrompts, ...prompts]),
      [cloudPrompts, prompts],
    ),
    promptCursors,
    setPromptCursor,
    answer: (taskId, prompt, reply) => {
      const local = localSessions.get(taskId);
      if (local) return local.answer(prompt, reply);
      if (!runs) return Promise.reject(new Error("Sign in first: type /login"));
      return runs.answer(reply);
    },
    composerFor,
    flashNotice,
  });

  const {
    openModelSheet,
    openEffortSheet,
    openModeSheet,
    pickFor,
    compact,
    onRunLive,
    onChatStarted,
    modelLabel,
    cycleMode,
    modeOf,
    onModes,
  } = useModels({
    startingFor: (paneId) =>
      startingOptions(loadPrefs().billing, placeFor(paneId)),
    layout,
    isLocal,
    localSessions: shownSessions,
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

  const account = useAccount({
    layout,
    setLayout,
    signedIn: chats !== undefined,
    placeFor,
    openModal,
    closeModal,
    notice,
    login,
    logout,
    onSignOut: () => {
      resetWork();
      setFresh(new Map());
    },
    runSetup,
    codexCloud: session?.codexCloud,
  });
  const { welcome, welcomeStep } = account;
  const mcpSheet = useMcpSheet({
    layout,
    openModal,
    closeModal,
    notice,
    mcp: session?.mcp,
  });
  const { onSubmit, pending, reopening, undelivered, delivered } = useSend({
    layout,
    setLayout,
    setFresh,
    chats,
    taskOf,
    local: { isLocal, localFor, clear: clearLocal, markActive },
    places: { placeFor, setPlace },
    composerFor,
    modalFor,
    openModelSheet,
    openEffortSheet,
    openModeSheet,
    pickFor,
    compact,
    openSearch: () => latestSearch.current?.toggle(),
    openHelp: () => setHelpOpen(true),
    openSettings: settings.toggle,
    repos: repoPicker,
    onChatStarted,
    setTitles,
    runShell,
    notice,
    account,
    mcpSheet,
  });
  // Chats with a message on its way; a new chat's message waits on its pane until the chat has a task.
  const pendingTaskIds = useMemo(
    () =>
      new Set([...pending.keys()].filter((id) => isLocal(id) || taskOf(id))),
    [pending, isLocal, taskOf],
  );
  const turns = useTurns({
    layout,
    runs: runs ?? null,
    taskOf,
    localSessions,
    pending: pendingTaskIds,
    listed: page.tasks ?? undefined,
  });
  const search = useSearch({
    work,
    recent: page.tasks,
    known,
    setLayout,
    working: turns.working,
    waiting: turns.waiting,
    local: { active: localActive, running: new Set(localSessions.keys()) },
  });
  latestSearch.current = search;

  // A chat's message on its way counts as a turn before its run says so; a new chat's is keyed by its pane.
  const working = useMemo(
    () => new Set([...turns.working, ...pending.keys()]),
    [turns.working, pending],
  );
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
    working,
    waiting: turns.waiting,
    titles,
    showToday,
    pinned,
    scope,
    lines: Math.max(0, area.height - CHROME_ROWS),
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
    showToday &&
    session?.today &&
    mainPane?.today &&
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

  const { boxes, paneAtDrop, typed, ...pointer } = usePointer({
    rows: sidebar.rows,
    activate: sidebar.activate,
    navigate: sidebar.navigate,
    setNavigating: sidebar.setNavigating,
    setCollapsed: sidebar.setCollapsed,
    setScope: switchScope,
    offset: sidebar.offset,
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

  const history = useHistory({ layout, setLayout });
  const titleOf = (pane: PaneNode): string => {
    if (pane.taskId === null) return pane.today ? "Today" : "New chat";
    return (
      titles.get(pane.taskId) ||
      taskOf(pane.taskId)?.title ||
      pane.title ||
      "Untitled"
    );
  };
  const { onKey, setOffer, setTurn, pickerFor } = useKeys({
    layout,
    setLayout,
    history,
    sidebar,
    search,
    settings,
    help: { open: helpOpen, close: () => setHelpOpen(false) },
    composerFor,
    modalFor,
    onModalKey,
    scrollPane,
    control,
    paneAtDrop,
    typed,
    cycleMode: (paneId, step) =>
      cycleMode(paneId, taskOf(findPane(layout, paneId)?.taskId ?? null), step),
    toggleSidebar: () => {
      track("sidebar narrowed", { narrow: !narrowSidebar });
      setNarrowSidebar(!narrowSidebar);
      savePrefs({ narrowSidebar: !narrowSidebar });
    },
    // Pins the chat under the sidebar cursor, or the focused pane's; a new chat has no task to pin yet.
    togglePin: () => {
      const row = sidebar.rows[sidebar.selectedIndex];
      const pane = findPane(layout, workspace.focusedPaneId);
      const chat = sidebarFocused
        ? row?.kind === "task" && row.taskId
          ? { id: row.taskId, title: row.title }
          : null
        : pane?.taskId
          ? { id: pane.taskId, title: titleOf(pane) }
          : null;
      if (!chat) return;
      const wasPinned = pinned.some((p) => p.id === chat.id);
      const next = wasPinned
        ? pinned.filter((p) => p.id !== chat.id)
        : [...pinned, chat];
      track("chat pinned", { pinned: !wasPinned });
      setPinned(next);
      savePrefs({ pinnedChats: next });
    },
    toggleScope: () => switchScope(scope === "mine" ? "all" : "mine"),
    repoPickerKey: repoPicker.onKey,
    notice,
  });
  useTerminalInput(mouse, { ...pointer, onKey });
  latestSubmit.current = onSubmit;

  // A run that starts signed out opens the sign-in sheet itself; a first run's sheet goes on to the welcome.
  const latestWelcome = useRef(welcome);
  latestWelcome.current = welcome;
  const signedOut = session === null;
  const focusedPaneId = workspace.focusedPaneId;
  useEffect(() => {
    if (signedOut) latestWelcome.current(focusedPaneId);
  }, [signedOut, focusedPaneId]);

  onBackground.current = (reply) => {
    const background = backgroundFromReply(reply);
    if (!background) return;
    applyBackground(background);
    for (const chat of allChats()) chat.invalidate();
    setThemeVersion((version) => version + 1);
  };

  const renderPane = (node: PaneNode): ReactElement => (
    <Pane
      title={titleOf(node)}
      paneTaskId={node.taskId}
      task={taskOf(node.taskId)}
      runs={runs ?? null}
      local={isLocal(node.taskId) ? shownSessions.get(node.taskId) : undefined}
      isLocalPane={runsLocally(node.id, node.taskId)}
      newChatPlace={placeFor(node.id)}
      banner={bannerLines({
        place: placeFor(node.id),
        cwd: process.cwd(),
        home: homedir(),
        repositories: repoPicker.reposFor(node.id),
        billing: loadPrefs().billing,
        model: modelLabel(node.id, null),
      })}
      billing={loadPrefs().billing}
      showContext={loadPrefs().showContext}
      mode={modeOf(node.id, node.taskId)}
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
      search={search.open && search.paneId === node.id ? search : null}
      onUndelivered={(at, sandboxGone) =>
        node.taskId && undelivered(node.id, node.taskId, at, sandboxGone)
      }
      onDelivered={() => node.taskId && delivered(node.taskId)}
      pendingShells={shellsFor(node.taskId)}
      onLines={(lines) => setLines(node.id, lines)}
      onOffer={(offer) => setOffer(node.id, offer)}
      picker={pickerFor(node.id)}
      modal={modalFor(node.id) ?? null}
      model={modelLabel(node.id, node.taskId, runModel(taskOf(node.taskId)))}
      // A cloud Claude Code or Codex run has no pi RPC, so its models, effort and commands stay unread.
      onRunLive={(taskId, runId) =>
        (isLocal(taskId) || taskOf(taskId)?.runtime === "pi") &&
        onRunLive(node.id, taskId, runId)
      }
      onTurn={(turn) => setTurn(node.id, turn)}
      onModes={onModes}
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

  if (search.open && search.paneId === null) return <Search search={search} />;
  if (helpOpen) return <Help />;
  if (settings.open) return <Settings settings={settings} />;
  if (welcomeStep)
    return (
      <Welcome
        step={welcomeStep}
        modal={modalFor(workspace.focusedPaneId)}
        notice={notice.shown?.text ?? null}
      />
    );

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
        offset={sidebar.offset}
        lines={sidebar.lines}
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
