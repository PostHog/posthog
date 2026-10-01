import { StdinBuffer } from "@earendil-works/pi-tui";
import type { CloudRegion, Task } from "@posthog/shared";
import {
  Box,
  type DOMElement,
  measureElement,
  useApp,
  useBoxMetrics,
  useInput,
} from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import { type ActionsLine, actionsSheet, canRun } from "../actions";
import { REGIONS } from "../auth";
import { currentRepository, type PiChats } from "../chats";
import type { ChatView } from "../chatView";
import { copyToClipboard } from "../clipboard";
import { isAppKey, isTyping } from "../composer";
import { messageOf } from "../errors";
import { useChatPlace } from "../hooks/useChatPlace";
import { useLocalChats } from "../hooks/useLocalChats";
import { useModels } from "../hooks/useModels";
import { useNotice } from "../hooks/useNotice";
import { usePaneViews } from "../hooks/usePaneViews";
import { useSheets } from "../hooks/useSheets";
import { useShell } from "../hooks/useShell";
import { useWorkList } from "../hooks/useWorkList";
import {
  activeWorkspace,
  allPanes,
  assignTask,
  closeFocused,
  cycleFocus,
  findPane,
  focusPane,
  focusSidebar,
  initialLayout,
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
import { type PiControl, parseSlash } from "../models";
import {
  type Click,
  hitTest,
  type MouseEvents,
  type Box as ScreenBox,
  type Wheel,
} from "../mouse";
import { openUrl } from "../openUrl";
import type { CloudRuns } from "../runs";
import { Gesture } from "../selection";
import { moveCursor, type SheetKey, sheetKey } from "../sheet";
import { parseShell } from "../shell";
import { DoublePress, shortcutFor } from "../shortcuts";
import {
  activateRow,
  cursorIndex,
  moveSelection,
  selectionKey,
  sidebarRows,
} from "../sidebar";
import { statusChips } from "../status";
import type { WorkList } from "../work";
import { Pane } from "./Pane";
import { HEADER_GAP, Sidebar } from "./Sidebar";

const CLOSE_CONFIRM_MS = 1_000;

function boxOf(element: DOMElement): ScreenBox {
  const { x, y, width, height } = measureElement(element);
  return { left: x + 1, top: y + 1, right: x + width, bottom: y + height };
}

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
  const { flashNotice, showNotice, clearNotice } = notice;
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
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<Map<string, string>>(new Map());
  // Each pane reports the agent's open action offer; the picker's cursor and dismissals live here.
  const offers = useRef(new Map<string, ActionsLine | null>());
  const [pickerIndex, setPickerIndex] = useState<Map<string, number>>(
    new Map(),
  );
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  // The cursor follows a row's identity, since previewing a chat can move rows.
  const [selected, setSelected] = useState<string | null>(null);
  // Arrows keep walking the sidebar after it hands focus to a chat, until a pane is clicked.
  const [navigating, setNavigating] = useState(false);
  const closeGuard = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  const escapes = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  // Panes whose run is mid-turn, so Esc knows what to stop.
  const runningTurns = useRef(
    new Map<string, { taskId: string; runId: string } | null>(),
  );
  const sidebarBox = useRef<DOMElement | null>(null);
  const paneBoxes = useRef(new Map<string, DOMElement>());
  const chatBoxes = useRef(new Map<string, DOMElement>());
  const prChips = useRef(
    new Map<string, { element: DOMElement; url: string }>(),
  );
  const newChatRepository = useMemo(() => currentRepository(), []);
  const chatArea = useRef<DOMElement | null>(null);
  const area = useBoxMetrics(chatArea);
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
    onSubmit: (paneId, text) => handlers.current.onSubmit(paneId, text),
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

  const openLoginSheet = (paneId: string, description: string): void => {
    openModal(
      paneId,
      {
        title: "Sign in to PostHog",
        description,
        items: REGIONS.map((region) => ({ label: region.label })),
        footer: "Enter to open your browser · Esc to cancel",
      },
      (index) => {
        const region = REGIONS[index];
        showNotice("Finish signing in with your browser…");
        login(region.id, () => {}).then(
          () => flashNotice(`Signed in to ${region.label}`),
          (error: unknown) =>
            flashNotice(`Sign-in failed: ${messageOf(error)}`),
        );
      },
    );
  };

  // A session's workspaces belong to its account, so signing out starts from one empty chat.
  const signOut = (): void => {
    logout();
    const fresh = initialLayout();
    setLayout(fresh);
    saveLayout(fresh);
    resetWork();
    setFresh(new Map());
    setPending(new Map());
    flashNotice("Signed out");
  };

  const { runShell, shellsFor } = useShell({
    taskOf,
    isLocal,
    localFor,
    control,
    composerFor,
    linesOf,
    flashNotice,
  });

  const onSubmit = (paneId: string, text: string): void => {
    const pane = findPane(layout, paneId);
    const current = taskOf(pane?.taskId ?? null);
    const textPrompt = modalFor(paneId)?.submitText;
    if (textPrompt) {
      textPrompt(text);
      return;
    }
    const slash = parseSlash(text);
    if (slash?.command === "model") {
      openModelSheet(paneId, current);
      return;
    }
    if (slash?.command === "new") {
      setLayout(newChat);
      return;
    }
    if (slash?.command === "clear") {
      const taskId = pane?.taskId ?? null;
      if (!taskId) flashNotice("There's nothing to clear yet");
      else if (!isLocal(taskId))
        flashNotice(
          "You can't clear a cloud run. Type /new to start a new chat",
        );
      else
        clearLocal(taskId).then(
          () => flashNotice("Cleared this chat"),
          (error: unknown) =>
            flashNotice(`Couldn't clear this chat: ${messageOf(error)}`),
        );
      return;
    }
    if (slash?.command === "local" || slash?.command === "cloud") {
      const mode = slash.command;
      setPlace(paneId, mode);
      flashNotice(
        mode === "local"
          ? `New chats run on this machine, in ${process.cwd()}`
          : "New chats run in the cloud",
      );
      return;
    }
    if (slash?.command === "login") {
      openLoginSheet(paneId, "Pick the PostHog you sign in to.");
      return;
    }
    if (slash?.command === "logout") {
      signOut();
      return;
    }
    const shell = parseShell(text);
    if (shell) {
      runShell(paneId, pane?.taskId ?? null, shell, text);
      return;
    }
    // Signed out, a message waits in the composer while the user signs in.
    if (!chats) {
      composerFor(paneId).setText(text);
      openLoginSheet(
        paneId,
        "Sign in to send this message. It stays in the composer.",
      );
      return;
    }
    setPending((messages) => new Map(messages).set(paneId, text));
    const clearPending = (): void =>
      setPending((messages) => {
        const next = new Map(messages);
        next.delete(paneId);
        return next;
      });
    const promptLocal = (taskId: string): Promise<void> => {
      markActive(taskId);
      return localFor(taskId).then((local) => local.prompt(text));
    };
    if (isLocal(pane?.taskId ?? null)) {
      promptLocal(pane?.taskId as string).catch((error: unknown) => {
        clearPending();
        flashNotice(`Couldn't send: ${messageOf(error)}`);
      });
      return;
    }
    // A local chat starts with its task row, so it is never only on this machine; without one, the message stays in the composer.
    if (!pane?.taskId && placeFor(paneId) === "local") {
      chats.createLocal(text).then(
        (task) => {
          setFresh((tasks) => new Map(tasks).set(task.id, task));
          setLayout((state) =>
            assignTask(state, paneId, task.id, task.title || text.slice(0, 80)),
          );
          promptLocal(task.id).catch((error: unknown) => {
            clearPending();
            flashNotice(`Couldn't send: ${messageOf(error)}`);
          });
        },
        (error: unknown) => {
          clearPending();
          composerFor(paneId).setText(text);
          flashNotice(
            `Couldn't start the chat: ${messageOf(error)}. Your message is still in the composer.`,
          );
        },
      );
      return;
    }
    (current ? chats.reply(current, text) : chats.start(text)).then(
      (task) => {
        setFresh((tasks) => new Map(tasks).set(task.id, task));
        if (!current) {
          const title = task.title || text.slice(0, 80);
          setLayout((state) => assignTask(state, paneId, task.id, title));
        }
      },
      (error: unknown) => {
        setPending((messages) => {
          const next = new Map(messages);
          next.delete(paneId);
          return next;
        });
        flashNotice(`Couldn't send: ${messageOf(error)}`);
      },
    );
  };

  const rows = useMemo(
    () =>
      sidebarRows({
        layout,
        work: page,
        collapsed,
        working: new Set(),
        known: new Map([...known, ...fresh]),
        signedIn: session !== null,
        local: { active: localActive, running: new Set(localSessions.keys()) },
      }),
    [
      layout,
      page,
      collapsed,
      known,
      fresh,
      session,
      localActive,
      localSessions,
    ],
  );
  const selectedIndex = cursorIndex(rows, selected);
  const workspace = activeWorkspace(layout);
  const sidebarFocused = layout.focus === "sidebar";

  const activate = (index: number): void => {
    const row = rows[index];
    if (!row) return;
    setSelected(selectionKey(row));
    const next = activateRow(layout, row);
    if (next === "viewMore") {
      loadMore();
    } else {
      setLayout(next);
    }
  };

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
      setCollapsed((current) => {
        const next = new Set(current);
        if (key.leftArrow) next.add(row.workspaceId);
        else next.delete(row.workspaceId);
        return next;
      });
    } else if (key.return) {
      setNavigating(rows[selectedIndex]?.kind === "task");
      activate(selectedIndex);
    }
  });

  // Clicking a row opens it like Enter; clicking elsewhere in the sidebar focuses it; clicking a pane focuses that pane.
  const onClick = (click: Click): void => {
    const sidebar = sidebarBox.current && boxOf(sidebarBox.current);
    if (sidebar && hitTest(click, [["sidebar", sidebar]])) {
      const onScreen = click.row - sidebar.top;
      const index = onScreen === 0 ? 0 : Math.max(0, onScreen - HEADER_GAP);
      const row = rows[index];
      if (
        row?.kind === "task" ||
        row?.kind === "workspace" ||
        row?.kind === "viewMore"
      ) {
        setNavigating(row.kind !== "viewMore");
        activate(index);
      } else {
        setLayout(focusSidebar);
      }
      return;
    }
    const pr = hitTest(
      click,
      [...prChips.current.values()].map(
        ({ element, url }) => [url, boxOf(element)] as [string, ScreenBox],
      ),
    );
    if (pr) {
      openUrl(pr[0]);
      return;
    }
    const panes = [...paneBoxes.current].map(
      ([paneId, element]) => [paneId, boxOf(element)] as [string, ScreenBox],
    );
    const hit = hitTest(click, panes);
    if (hit) {
      setNavigating(false);
      setLayout((current) => focusPane(current, hit[0]));
      const chatBox = chatBoxes.current.get(hit[0]);
      const box = chatBox && boxOf(chatBox);
      const chat = chatIn(hit[0]);
      if (!box || !hitTest(click, [["chat", box]])) return;
      const link = chat.linkAt(click.row - box.top, click.column - box.left);
      if (link) openUrl(link);
      else if (chat.toggleAt(click.row - box.top)) repaint();
    }
  };
  const onMove = (move: Click): void => {
    let changed = false;
    for (const [paneId, element] of chatBoxes.current) {
      const box = boxOf(element);
      const row = hitTest(move, [["chat", box]]) ? move.row - box.top : null;
      if (chatIn(paneId).hoverAt(row)) changed = true;
    }
    if (changed) repaint();
  };
  const onWheel = (wheel: Wheel): void => {
    const panes = [...paneBoxes.current].map(
      ([paneId, element]) => [paneId, boxOf(element)] as [string, ScreenBox],
    );
    const hit = hitTest(wheel, panes);
    if (hit) scrollPane(hit[0], wheel.delta * 3);
  };
  // Typing in a focused pane goes to its composer; the app's own keys stay with the app.
  // Moves the sidebar cursor and hands focus to that chat, so typing goes straight to it.
  const navigate = (step: 1 | -1): void => {
    const next = moveSelection(rows, selectedIndex, step);
    const row = rows[next];
    setSelected(selectionKey(row));
    const opened = row && activateRow(layout, row);
    if (!opened || opened === "viewMore") {
      setNavigating(false);
      setLayout(focusSidebar);
      return;
    }
    setNavigating(true);
    setLayout(opened);
  };

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

  // A press starts a click or, once the pointer moves, a selection in the chat it landed on.
  const gesture = useRef(new Gesture());
  const selecting = useRef<{ chat: ChatView; box: ScreenBox } | null>(null);
  const selectIn = (from: Click, to: Click): void => {
    const target = selecting.current;
    if (!target) return;
    const local = (at: Click): Click => ({
      row: at.row - target.box.top,
      column: at.column - target.box.left,
    });
    target.chat.select(local(from), local(to));
    repaint();
  };
  const onPress = (at: Click): void => {
    gesture.current.press(at);
    for (const chat of allChats()) chat.clearSelection();
    selecting.current = null;
    for (const [paneId, element] of chatBoxes.current) {
      const box = boxOf(element);
      if (hitTest(at, [["chat", box]]))
        selecting.current = {
          chat: chatIn(paneId),
          box,
        };
    }
    repaint();
  };
  const onDrag = (at: Click): void => {
    const range = gesture.current.drag(at);
    if (range) selectIn(range.from, range.to);
  };
  const onRelease = (at: Click): void => {
    const end = gesture.current.release(at);
    if (end?.kind === "click") onClick(end.at);
    if (end?.kind !== "select" || !selecting.current) return;
    selectIn(end.from, end.to);
    const text = selecting.current.chat.selectedText();
    if (!text.trim()) return;
    copyToClipboard(text);
    flashNotice("Copied to clipboard");
  };

  const handlers = useRef({
    onPress,
    onDrag,
    onRelease,
    onMove,
    onWheel,
    onKey,
    onSubmit,
  });
  handlers.current = {
    onPress,
    onDrag,
    onRelease,
    onMove,
    onWheel,
    onKey,
    onSubmit,
  };

  useEffect(() => {
    if (!mouse) return;
    const press = (at: Click): void => handlers.current.onPress(at);
    const drag = (at: Click): void => handlers.current.onDrag(at);
    const release = (at: Click): void => handlers.current.onRelease(at);
    const wheel = (at: Wheel): void => handlers.current.onWheel(at);
    const move = (at: Click): void => handlers.current.onMove(at);
    const keys = new StdinBuffer();
    keys.on("data", (sequence) => handlers.current.onKey(sequence));
    keys.on("paste", (text) =>
      handlers.current.onKey(`\x1b[200~${text}\x1b[201~`),
    );
    const raw = (data: string): void => keys.process(data);
    mouse.on("press", press);
    mouse.on("drag", drag);
    mouse.on("release", release);
    mouse.on("wheel", wheel);
    mouse.on("move", move);
    mouse.on("keys", raw);
    return () => {
      mouse.off("press", press);
      mouse.off("drag", drag);
      mouse.off("release", release);
      mouse.off("wheel", wheel);
      mouse.off("move", move);
      mouse.off("keys", raw);
      keys.destroy();
    };
  }, [mouse]);

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
          ref={(element) => {
            if (element) paneBoxes.current.set(node.id, element);
            else paneBoxes.current.delete(node.id);
          }}
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
            onPrChip={(element, url) => {
              if (element && url)
                prChips.current.set(node.id, { element, url });
              else prChips.current.delete(node.id);
            }}
            onChatBox={(element) => {
              if (element) chatBoxes.current.set(node.id, element);
              else chatBoxes.current.delete(node.id);
            }}
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
        boxRef={sidebarBox}
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
