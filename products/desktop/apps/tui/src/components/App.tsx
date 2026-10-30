import type { CloudRegion, Task } from "@posthog/shared";
import { Box, type DOMElement, useBoxMetrics } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import { currentRepository, type PiChats } from "../chats";
import { useChatPlace } from "../hooks/useChatPlace";
import { useKeys } from "../hooks/useKeys";
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
  type LayoutNode,
  type LayoutState,
  loadLayout,
  type PaneNode,
  paneIds,
  saveLayout,
  splitSizes,
} from "../layout";
import type { LocalSession } from "../local";
import type { PiControl } from "../models";
import type { MouseEvents } from "../mouse";
import type { CloudRuns } from "../runs";
import { statusChips } from "../status";
import type { WorkList } from "../work";
import { Pane } from "./Pane";
import { Sidebar } from "./Sidebar";

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
  const { flashNotice } = notice;
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
  });
  const workspace = activeWorkspace(layout);
  const sidebarFocused = layout.focus === "sidebar";

  const { onKey, setOffer, setTurn, pickerFor } = useKeys({
    layout,
    setLayout,
    sidebar,
    composerFor,
    modalFor,
    onModalKey,
    scrollPane,
    control,
    notice,
  });

  const { boxes, ...pointer } = usePointer({
    rows: sidebar.rows,
    activate: sidebar.activate,
    setNavigating: sidebar.setNavigating,
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
            onOffer={(offer) => setOffer(node.id, offer)}
            picker={pickerFor(node.id)}
            modal={modalFor(node.id) ?? null}
            model={modelName(node.id, node.taskId)}
            onRunLive={(taskId, runId) => onRunLive(node.id, taskId, runId)}
            onTurn={(turn) => setTurn(node.id, turn)}
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
        rows={sidebar.rows}
        focused={sidebarFocused}
        selectedIndex={sidebar.selectedIndex}
        activePaneId={workspace.focusedPaneId}
      />
      <Box ref={chatArea} flexGrow={1}>
        {area.hasMeasured &&
          renderNode(workspace.root, null, area.width, area.height)}
      </Box>
    </Box>
  );
}
