import type { CloudRegion, Task } from "@posthog/shared";
import { Box, type DOMElement, useApp, useBoxMetrics, useInput } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import { type ActionsLine, actionsSheet, canRun } from "../actions";
import { currentRepository, type PiChats } from "../chats";
import { isAppKey, isTyping } from "../composer";
import { messageOf } from "../errors";
import { useChatPlace } from "../hooks/useChatPlace";
import { useLocalChats } from "../hooks/useLocalChats";
import { useModels } from "../hooks/useModels";
import { useNotice } from "../hooks/useNotice";
import { usePaneViews } from "../hooks/usePaneViews";
import { usePointer } from "../hooks/usePointer";
import { useSend } from "../hooks/useSend";
import { useSheets } from "../hooks/useSheets";
import { useShell } from "../hooks/useShell";
import { useSidebar } from "../hooks/useSidebar";
import { useTerminalInput } from "../hooks/useTerminalInput";
import { useWorkList } from "../hooks/useWorkList";
import {
  activeWorkspace,
  allPanes,
  closeFocused,
  cycleFocus,
  focusPane,
  type LayoutNode,
  type LayoutState,
  loadLayout,
  newChat,
  type PaneNode,
  paneIds,
  saveLayout,
  splitFocused,
  splitSizes,
} from "../layout";
import type { LocalSession } from "../local";
import type { PiControl } from "../models";
import type { MouseEvents } from "../mouse";
import type { CloudRuns } from "../runs";
import { moveCursor, type SheetKey, sheetKey } from "../sheet";
import { DoublePress, shortcutFor } from "../shortcuts";
import { statusChips } from "../status";
import type { WorkList } from "../work";
import { Pane } from "./Pane";
import { Sidebar } from "./Sidebar";

const CLOSE_CONFIRM_MS = 1_000;

// A split draws one line between neighbours: left of each column after the first, above each row after the first.
function dividerProps(divider: "left" | "top" | null) {
  return divider
    ? {
        borderStyle: "single" as const,
        borderColor: "gray",
        borderDimColor: true,
        borderTop: divider === "top",
        borderLeft: divider === "left",
        borderRight: false,
        borderBottom: false,
      }
    : {};
}

export interface Session {
  work: WorkList;
  runs: CloudRuns;
  chats: PiChats;
  control: (taskId: string, runId: string) => PiControl;
  startLocal: (id: string) => Promise<LocalSession>;
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
  const { flashNotice, clearNotice } = notice;
  const [layout, setLayout] = useState<LayoutState>(loadLayout);
  // Tasks this app just started or resumed; they win until the list shows the same run.
  const [fresh, setFresh] = useState<Map<string, Task>>(new Map());
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
  const { exit } = useApp();
  // Each pane reports the agent's open action offer; the picker's cursor and dismissals live here.
  const offers = useRef(new Map<string, ActionsLine | null>());
  const [pickerIndex, setPickerIndex] = useState<Map<string, number>>(
    new Map(),
  );
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const closeGuard = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  const escapes = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  // Panes whose run is mid-turn, so Esc knows what to stop.
  const runningTurns = useRef(
    new Map<string, { taskId: string; runId: string } | null>(),
  );
  const newChatRepository = useMemo(() => currentRepository(), []);
  const chatArea = useRef<DOMElement | null>(null);
  const area = useBoxMetrics(chatArea);
  // Composers outlive renders, so they submit through the latest onSubmit.
  const latestSubmit = useRef<(paneId: string, text: string) => void>(() => {});
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
    onSubmit: (paneId, text) => latestSubmit.current(paneId, text),
  });

  useEffect(() => saveLayout(layout), [layout]);

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

  const { modalFor, openModal, onModalKey } = useSheets({
    layout,
    prompts,
    promptCursors,
    setPromptCursor,
    localSessions,
    composerFor,
    flashNotice,
  });

  const { openModelSheet, onRunLive, modelName } = useModels({
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

  const { onSubmit, pending } = useSend({
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
    runShell,
    notice,
    login,
    logout,
  });

  const {
    rows,
    selectedIndex,
    navigating,
    setNavigating,
    activate,
    navigate,
    setCollapsed,
  } = useSidebar({
    layout,
    setLayout,
    page,
    known,
    fresh,
    signedIn: session !== null,
    localActive,
    localSessions,
    loadMore,
  });
  const workspace = activeWorkspace(layout);
  const sidebarFocused = layout.focus === "sidebar";

  const close = (): void => {
    if (!closeGuard.current.press(Date.now())) {
      const last =
        layout.workspaces.length === 1 && paneIds(workspace.root).length === 1;
      flashNotice(
        `Press again to ${last ? "quit" : "close this chat"}`,
        CLOSE_CONFIRM_MS,
      );
      return;
    }
    clearNotice();
    const next = closeFocused(layout);
    if (next === "quit") exit();
    else setLayout(next);
  };

  useInput((input, key) => {
    const shortcut = shortcutFor(input, key);
    if (shortcut === "close") return close();
    // Layout and chats are saved as they change, so quitting loses nothing.
    if (shortcut === "quit") return exit();
    if (shortcut === "reload") {
      // Set by cli.mjs, which owns the Vite server; absent when the app runs without it.
      (
        globalThis as { __posthogTuiReload?: () => void }
      ).__posthogTuiReload?.();
      return;
    }
    if (shortcut === "newChat") {
      setLayout(newChat);
      return;
    }
    if (shortcut) {
      const direction = shortcut === "splitDown" ? "column" : "row";
      setLayout((current) => splitFocused(current, direction));
      return;
    }
    if (key.tab) {
      setNavigating(false);
      setLayout((current) => cycleFocus(current, key.shift ? -1 : 1));
      return;
    }
    if (!sidebarFocused) {
      if (navigating && (key.upArrow || key.downArrow)) {
        navigate(key.downArrow ? 1 : -1);
      }
      if (key.pageUp) scrollPane(workspace.focusedPaneId, -10);
      if (key.pageDown) scrollPane(workspace.focusedPaneId, 10);
      return;
    }
    if (key.escape) {
      setLayout((current) => focusPane(current, workspace.focusedPaneId));
    } else if (key.downArrow || key.upArrow) {
      navigate(key.downArrow ? 1 : -1);
    } else if (key.leftArrow || key.rightArrow) {
      const row = rows[selectedIndex];
      if (row?.kind !== "workspace") return;
      setCollapsed(row.workspaceId, key.leftArrow);
    } else if (key.return) {
      setNavigating(rows[selectedIndex]?.kind === "task");
      activate(selectedIndex);
    }
  });

  // Typing in a focused pane goes to its composer; the app's own keys stay with the app.
  const onKey = (sequence: string): void => {
    if (isAppKey(sequence)) return;
    const paneId = workspace.focusedPaneId;
    // Typing from the sidebar carries on in the selected chat's composer.
    if (layout.focus === "sidebar") {
      if (!isTyping(sequence)) return;
      setNavigating(true);
      setLayout((current) => focusPane(current, paneId));
      composerFor(paneId).handleInput(sequence);
      return;
    }
    const key = sheetKey(sequence);
    const modal = modalFor(paneId);
    if (modal?.submitText && key?.kind !== "dismiss") {
      composerFor(paneId).handleInput(sequence);
      return;
    }
    if (modal) {
      if (key) onModalKey(paneId, modal, key);
      return;
    }
    if (navigating && (key?.kind === "up" || key?.kind === "down")) return;
    const composer = composerFor(paneId);
    const offer = offers.current.get(paneId);
    // With an open offer and nothing typed, arrows and Enter drive its sheet.
    if (
      offer &&
      !dismissed.has(offer.id) &&
      key &&
      key.kind !== "number" &&
      composer.isEmpty()
    ) {
      onOfferKey(paneId, offer, key);
      return;
    }
    // Esc stops a running turn; a second Esc straight after clears what is typed.
    if (key?.kind === "dismiss" && !composer.showingSuggestions()) {
      const turn = runningTurns.current.get(paneId);
      if (turn && control) {
        flashNotice("Stopping…");
        control(turn.taskId, turn.runId)
          .abort()
          .then(
            () => flashNotice("Stopped"),
            (error: unknown) =>
              flashNotice(`Couldn't stop: ${messageOf(error)}`),
          );
      }
      if (escapes.current.press(Date.now())) composer.clear();
      else if (!turn && !composer.isEmpty())
        flashNotice("Press Esc again to clear");
      return;
    }
    composer.handleInput(sequence);
  };

  const onOfferKey = (
    paneId: string,
    offer: ActionsLine,
    key: SheetKey,
  ): void => {
    const sheet = actionsSheet(offer);
    const index = pickerIndex.get(paneId) ?? 0;
    if (key.kind === "up" || key.kind === "down") {
      const next = moveCursor(sheet, index, key.kind === "up" ? -1 : 1);
      setPickerIndex((indexes) => new Map(indexes).set(paneId, next));
      return;
    }
    const action = offer.actions[Math.min(index, offer.actions.length - 1)];
    if (key.kind === "choose" && !canRun(action)) return;
    setDismissed((ids) => new Set(ids).add(offer.id));
    if (key.kind === "choose" && action.kind === "compose") {
      const next = newChat(layout);
      setLayout(next);
      composerFor(activeWorkspace(next).focusedPaneId).setText(action.prompt);
    }
  };

  const { boxes, ...pointer } = usePointer({
    rows,
    activate,
    setNavigating,
    setLayout,
    chatIn,
    chats: allChats,
    scrollPane,
    repaint,
    flashNotice,
  });
  useTerminalInput(mouse, { ...pointer, onKey });
  latestSubmit.current = onSubmit;

  const titleOf = (pane: PaneNode): string => {
    if (pane.taskId === null) return "New chat";
    return taskOf(pane.taskId)?.title || pane.title || "Untitled";
  };

  // Splits get whole-cell sizes worked out here; flex layout rounds half cells and leaves gaps.
  const renderNode = (
    node: LayoutNode,
    divider: "left" | "top" | null,
    width: number,
    height: number,
  ): ReactElement => {
    if (node.kind === "pane") {
      return (
        <Box
          key={node.id}
          ref={(element) => boxes.setPane(node.id, element)}
          width={width}
          height={height}
          flexDirection="column"
          {...dividerProps(divider)}
        >
          <Pane
            title={titleOf(node)}
            paneTaskId={node.taskId}
            task={taskOf(node.taskId)}
            runs={runs ?? null}
            local={
              isLocal(node.taskId) ? localSessions.get(node.taskId) : undefined
            }
            isLocalPane={isLocal(node.taskId)}
            newChatPlace={placeFor(node.id)}
            chat={chatFor(node.id, node.taskId)}
            composer={composerFor(node.id)}
            pending={pending.get(node.id) ?? null}
            pendingShells={shellsFor(node.taskId)}
            onLines={(lines) => setLines(node.id, lines)}
            onOffer={(offer) => offers.current.set(node.id, offer)}
            picker={{
              index: pickerIndex.get(node.id) ?? 0,
              dismissed,
            }}
            modal={modalFor(node.id) ?? null}
            model={modelName(node.id, node.taskId)}
            onRunLive={(taskId, runId) => onRunLive(node.id, taskId, runId)}
            onTurn={(turn) => runningTurns.current.set(node.id, turn)}
            chips={
              isLocal(node.taskId) || !node.taskId
                ? statusChips(
                    undefined,
                    newChatRepository,
                    isLocal(node.taskId) ? "local" : placeFor(node.id),
                  )
                : taskOf(node.taskId)
                  ? statusChips(taskOf(node.taskId), newChatRepository)
                  : []
            }
            onPrChip={(element, url) => boxes.setPrChip(node.id, element, url)}
            onChatBox={(element) => boxes.setChat(node.id, element)}
            focused={!sidebarFocused && node.id === workspace.focusedPaneId}
          />
        </Box>
      );
    }
    const across = node.direction === "row";
    // This split's own divider takes a row or column before its children share the rest.
    const innerWidth = width - (divider === "left" ? 1 : 0);
    const innerHeight = height - (divider === "top" ? 1 : 0);
    const sizes = splitSizes(
      across ? innerWidth : innerHeight,
      node.children.length,
    );
    return (
      <Box
        key={paneIds(node).join()}
        flexDirection={node.direction}
        width={width}
        height={height}
        {...dividerProps(divider)}
      >
        {node.children.map((child, index) =>
          renderNode(
            child,
            index === 0 ? null : across ? "left" : "top",
            across ? sizes[index] : innerWidth,
            across ? innerHeight : sizes[index],
          ),
        )}
      </Box>
    );
  };

  // A spare row under everything keeps bottom composers off the window's edge.
  return (
    <Box flexGrow={1} paddingBottom={1}>
      <Sidebar
        boxRef={boxes.sidebar}
        notice={notice.notice}
        rows={rows}
        focused={sidebarFocused}
        selectedIndex={selectedIndex}
        activePaneId={workspace.focusedPaneId}
      />
      <Box ref={chatArea} flexGrow={1}>
        {area.hasMeasured &&
          renderNode(workspace.root, null, area.width, area.height)}
      </Box>
    </Box>
  );
}
