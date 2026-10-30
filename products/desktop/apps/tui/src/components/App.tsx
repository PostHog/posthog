import { StdinBuffer } from "@earendil-works/pi-tui";
import type { Task } from "@posthog/shared";
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
import type { PiChats } from "../chats";
import { ChatView } from "../chatView";
import { Composer, isAppKey, isTyping } from "../composer";
import {
  activeWorkspace,
  assignTask,
  closeFocused,
  cycleFocus,
  focusPane,
  focusSidebar,
  type LayoutNode,
  type LayoutState,
  loadLayout,
  newChat,
  type PaneNode,
  paneIds,
  panes,
  saveLayout,
  splitFocused,
  splitSizes,
} from "../layout";
import {
  type ModelChoice,
  modelSheet,
  type PiControl,
  parseSlash,
} from "../models";
import {
  type Click,
  hitTest,
  type MouseEvents,
  type Box as ScreenBox,
  type Wheel,
} from "../mouse";
import type { CloudRuns } from "../runs";
import { moveCursor, type Sheet, type SheetKey, sheetKey } from "../sheet";
import { DoublePress, shortcutFor } from "../shortcuts";
import {
  activateRow,
  cursorIndex,
  indicatorFor,
  moveSelection,
  selectionKey,
  sidebarRows,
  type WorkPage,
} from "../sidebar";
import type { WorkList } from "../work";
import { Pane } from "./Pane";
import { HEADER_GAP, Sidebar } from "./Sidebar";

const PAGE_SIZE = 10;

const messageOf = (error: unknown): string =>
  error instanceof Error ? error.message : String(error);

interface OpenModal {
  sheet: Sheet;
  index: number;
  choose: (index: number) => void;
}
const REFRESH_MS = 10_000;
const CLOSE_CONFIRM_MS = 1_000;
const SEND_ERROR_MS = 8_000;
// Log entries per preloaded run: roughly the last ten messages.
const PREVIEW_ENTRIES = 300;

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

export function App({
  work,
  runs,
  chats,
  control,
  mouse,
}: {
  work: WorkList;
  runs: CloudRuns;
  chats: PiChats;
  control: (taskId: string, runId: string) => PiControl;
  mouse?: MouseEvents;
}): ReactElement {
  const { exit } = useApp();
  const [layout, setLayout] = useState<LayoutState>(loadLayout);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [page, setPage] = useState<WorkPage>({
    tasks: null,
    hasMore: false,
    loadingMore: false,
    error: null,
  });
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [known, setKnown] = useState<Map<string, Task>>(new Map());
  // Tasks this app just started or resumed; they win until the list shows the same run.
  const [fresh, setFresh] = useState<Map<string, Task>>(new Map());
  const [pending, setPending] = useState<Map<string, string>>(new Map());
  // Each pane reports the agent's open action offer; the picker's cursor and dismissals live here.
  const offers = useRef(new Map<string, ActionsLine | null>());
  const [pickerIndex, setPickerIndex] = useState<Map<string, number>>(
    new Map(),
  );
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  // Modal sheets the app opened, one per pane; they take the pane's keys until closed.
  const [modals, setModals] = useState<Map<string, OpenModal>>(new Map());
  // Models: the last list a live run gave us, each task's model, and picks held until a pane's run is live.
  const knownModels = useRef<ModelChoice[] | null>(null);
  const [taskModels, setTaskModels] = useState<Map<string, ModelChoice>>(
    new Map(),
  );
  const [heldModels, setHeldModels] = useState<Map<string, ModelChoice>>(
    new Map(),
  );
  const appliedHolds = useRef(new Set<string>());
  const closeModal = (paneId: string): void =>
    setModals((current) => {
      const next = new Map(current);
      next.delete(paneId);
      return next;
    });
  // The cursor follows a row's identity, since previewing a chat can move rows.
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Arrows keep walking the sidebar after it hands focus to a chat, until a pane is clicked.
  const [navigating, setNavigating] = useState(false);
  const closeGuard = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  const sidebarBox = useRef<DOMElement | null>(null);
  const paneBoxes = useRef(new Map<string, DOMElement>());
  const chatArea = useRef<DOMElement | null>(null);
  const area = useBoxMetrics(chatArea);
  const chatViews = useRef(new Map<string, ChatView>());
  // Scrolling happens inside ChatView, so a tick tells React to repaint.
  const [, repaint] = useState(0);
  // Keyed by pane and task, so a pane that switches task starts that chat at its latest message.
  const chatFor = (key: string): ChatView => {
    let chat = chatViews.current.get(key);
    if (!chat) {
      chat = new ChatView();
      chatViews.current.set(key, chat);
    }
    return chat;
  };
  const composers = useRef(new Map<string, Composer>());
  const composerFor = (paneId: string): Composer => {
    let composer = composers.current.get(paneId);
    if (!composer) {
      composer = new Composer(
        () => repaint((tick) => tick + 1),
        (text) => handlers.current.onSubmit(paneId, text),
      );
      composers.current.set(paneId, composer);
    }
    return composer;
  };
  const scrollPane = (paneId: string, lines: number): void => {
    const pane = layout.workspaces
      .flatMap((w) => panes(w.root))
      .find((candidate) => candidate.id === paneId);
    chatFor(`${paneId}:${pane?.taskId ?? null}`).scrollBy(lines);
    repaint((tick) => tick + 1);
  };

  useEffect(() => saveLayout(layout), [layout]);

  useEffect(() => {
    let cancelled = false;
    const refresh = (): void => {
      work.listRecent(limit).then(
        ({ tasks, hasMore }) => {
          if (!cancelled) {
            setPage({ tasks, hasMore, loadingMore: false, error: null });
          }
        },
        (error: unknown) => {
          if (!cancelled) {
            setPage((current) => ({
              ...current,
              loadingMore: false,
              error: error instanceof Error ? error.message : String(error),
            }));
          }
        },
      );
    };
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [work, limit]);

  // Preloads each listed cloud run's recent messages, one at a time, so opening one shows them at once.
  const prefetched = useRef(new Set<string>());
  useEffect(() => {
    const pending = (page.tasks ?? []).flatMap((task) => {
      const run = task.latest_run;
      return run &&
        run.environment !== "local" &&
        !prefetched.current.has(run.id)
        ? [{ taskId: task.id, runId: run.id }]
        : [];
    });
    for (const { runId } of pending) prefetched.current.add(runId);
    void (async () => {
      for (const { taskId, runId } of pending) {
        await runs.prefetch(taskId, runId, PREVIEW_ENTRIES).catch(() => {
          prefetched.current.delete(runId);
        });
      }
    })();
  }, [runs, page.tasks]);

  // Open tasks outside the recent page are fetched once each, so they keep a title and a transcript.
  const openTaskIds = layout.workspaces
    .flatMap((w) => panes(w.root))
    .flatMap((pane) => (pane.taskId ? [pane.taskId] : []));
  const missing = page.tasks
    ? openTaskIds.filter(
        (id) => !known.has(id) && !page.tasks?.some((task) => task.id === id),
      )
    : [];
  const missingKey = missing.join();
  useEffect(() => {
    for (const taskId of missingKey ? missingKey.split(",") : []) {
      work.get(taskId).then(
        (task) => setKnown((current) => new Map(current).set(taskId, task)),
        () => {},
      );
    }
  }, [work, missingKey]);
  const taskOf = (taskId: string | null): Task | undefined => {
    if (!taskId) return undefined;
    const listed = page.tasks?.find((task) => task.id === taskId);
    const recent = fresh.get(taskId);
    if (recent && recent.latest_run?.id !== listed?.latest_run?.id)
      return recent;
    return listed ?? known.get(taskId);
  };

  const openModal = (
    paneId: string,
    sheet: Sheet,
    choose: (index: number) => void,
  ): void => {
    const current = sheet.items.findIndex((item) => item.current);
    setModals((open) =>
      new Map(open).set(paneId, { sheet, index: Math.max(0, current), choose }),
    );
  };

  const openModelSheet = (paneId: string, task: Task | undefined): void => {
    const run = task?.latest_run;
    if (task && run && indicatorFor(task, false) === "alive") {
      const live = control(task.id, run.id);
      setNotice("Loading models…");
      live.models().then(
        ({ available, current }) => {
          setNotice(null);
          knownModels.current = available;
          if (current)
            setTaskModels((models) => new Map(models).set(task.id, current));
          openModal(
            paneId,
            modelSheet(available, current, "Switches this chat's model now."),
            (index) => {
              const model = available[index];
              live.setModel(model).then(
                () =>
                  setTaskModels((models) =>
                    new Map(models).set(task.id, model),
                  ),
                (error: unknown) =>
                  flashNotice(`Couldn't switch model: ${messageOf(error)}`),
              );
            },
          );
        },
        (error: unknown) =>
          flashNotice(`Couldn't load models: ${messageOf(error)}`),
      );
      return;
    }
    const available = knownModels.current;
    if (!available) {
      flashNotice(
        "The model list comes from a running chat. Send a message first.",
      );
      return;
    }
    const held =
      heldModels.get(paneId) ?? (task ? taskModels.get(task.id) : undefined);
    openModal(
      paneId,
      modelSheet(
        available,
        held ?? null,
        "Applies once this chat's run starts.",
      ),
      (index) =>
        setHeldModels((models) =>
          new Map(models).set(paneId, available[index]),
        ),
    );
  };

  // A pick made while the run was not live is applied as soon as its sandbox is.
  const onRunLive = (paneId: string, taskId: string, runId: string): void => {
    const held = heldModels.get(paneId);
    if (!held || appliedHolds.current.has(runId)) return;
    appliedHolds.current.add(runId);
    control(taskId, runId)
      .setModel(held)
      .then(
        () => {
          setTaskModels((models) => new Map(models).set(taskId, held));
          setHeldModels((models) => {
            const next = new Map(models);
            next.delete(paneId);
            return next;
          });
        },
        (error: unknown) =>
          flashNotice(`Couldn't switch model: ${messageOf(error)}`),
      );
  };

  const flashNotice = (text: string): void => {
    setNotice(text);
    setTimeout(() => setNotice(null), SEND_ERROR_MS);
  };

  const onSubmit = (paneId: string, text: string): void => {
    const pane = layout.workspaces
      .flatMap((w) => panes(w.root))
      .find((candidate) => candidate.id === paneId);
    const current = taskOf(pane?.taskId ?? null);
    const slash = parseSlash(text);
    if (slash?.command === "model") {
      openModelSheet(paneId, current);
      return;
    }
    if (slash?.command === "new") {
      setLayout(newChat);
      return;
    }
    setPending((messages) => new Map(messages).set(paneId, text));
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
        setNotice(
          `Couldn't send: ${error instanceof Error ? error.message : String(error)}`,
        );
        setTimeout(() => setNotice(null), SEND_ERROR_MS);
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
      }),
    [layout, page, collapsed, known, fresh],
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
      setPage((current) => ({ ...current, loadingMore: true }));
      setLimit((current) => current + PAGE_SIZE);
    } else {
      setLayout(next);
    }
  };

  const close = (): void => {
    if (!closeGuard.current.press(Date.now())) {
      const last =
        layout.workspaces.length === 1 && paneIds(workspace.root).length === 1;
      setNotice(`Press again to ${last ? "quit" : "close this chat"}`);
      setTimeout(() => setNotice(null), CLOSE_CONFIRM_MS);
      return;
    }
    setNotice(null);
    const next = closeFocused(layout);
    if (next === "quit") exit();
    else setLayout(next);
  };

  useInput((input, key) => {
    const shortcut = shortcutFor(input, key);
    if (shortcut === "close") return close();
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
    const panes = [...paneBoxes.current].map(
      ([paneId, element]) => [paneId, boxOf(element)] as [string, ScreenBox],
    );
    const hit = hitTest(click, panes);
    if (hit) {
      setNavigating(false);
      setLayout((current) => focusPane(current, hit[0]));
    }
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
    const modal = modals.get(paneId);
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
    composer.handleInput(sequence);
  };

  const onModalKey = (
    paneId: string,
    modal: OpenModal,
    key: SheetKey,
  ): void => {
    if (key.kind === "up" || key.kind === "down") {
      const index = moveCursor(
        modal.sheet,
        modal.index,
        key.kind === "up" ? -1 : 1,
      );
      setModals((current) => new Map(current).set(paneId, { ...modal, index }));
      return;
    }
    if (key.kind === "dismiss") {
      closeModal(paneId);
      return;
    }
    const index = key.kind === "number" ? key.index : modal.index;
    const item = modal.sheet.items[index];
    if (!item || item.disabled) return;
    closeModal(paneId);
    modal.choose(index);
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

  const handlers = useRef({ onClick, onWheel, onKey, onSubmit });
  handlers.current = { onClick, onWheel, onKey, onSubmit };

  useEffect(() => {
    if (!mouse) return;
    const click = (at: Click): void => handlers.current.onClick(at);
    const wheel = (at: Wheel): void => handlers.current.onWheel(at);
    const keys = new StdinBuffer();
    keys.on("data", (sequence) => handlers.current.onKey(sequence));
    keys.on("paste", (text) =>
      handlers.current.onKey(`\x1b[200~${text}\x1b[201~`),
    );
    const raw = (data: string): void => keys.process(data);
    mouse.on("click", click);
    mouse.on("wheel", wheel);
    mouse.on("keys", raw);
    return () => {
      mouse.off("click", click);
      mouse.off("wheel", wheel);
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
            runs={runs}
            chat={chatFor(`${node.id}:${node.taskId}`)}
            composer={composerFor(node.id)}
            pending={pending.get(node.id) ?? null}
            onOffer={(offer) => offers.current.set(node.id, offer)}
            picker={{
              index: pickerIndex.get(node.id) ?? 0,
              dismissed,
            }}
            modal={modals.get(node.id) ?? null}
            model={
              heldModels.get(node.id)?.name ??
              (node.taskId ? taskModels.get(node.taskId)?.name : undefined)
            }
            onRunLive={(taskId, runId) => onRunLive(node.id, taskId, runId)}
            focused={!sidebarFocused && node.id === workspace.focusedPaneId}
          />
        </Box>
      );
    }
    const across = node.direction === "row";
    const sizes = splitSizes(across ? width : height, node.children.length);
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
            across ? sizes[index] : width,
            across ? height : sizes[index],
          ),
        )}
      </Box>
    );
  };

  return (
    <Box flexGrow={1}>
      <Sidebar
        boxRef={sidebarBox}
        notice={notice}
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
