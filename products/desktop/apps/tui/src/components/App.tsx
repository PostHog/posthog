import { StdinBuffer } from "@earendil-works/pi-tui";
import type { Task } from "@posthog/shared";
import { Box, type DOMElement, measureElement, useApp, useInput } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import { type ActionsLine, canRun, pickerKey } from "../actions";
import type { PiChats } from "../chats";
import { ChatView } from "../chatView";
import { Composer, isAppKey } from "../composer";
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
} from "../layout";
import {
  type Click,
  hitTest,
  type MouseEvents,
  type Box as ScreenBox,
  type Wheel,
} from "../mouse";
import type { CloudRuns } from "../runs";
import { DoublePress, shortcutFor } from "../shortcuts";
import {
  activateRow,
  firstSelectable,
  moveSelection,
  sidebarRows,
  type WorkPage,
} from "../sidebar";
import type { WorkList } from "../work";
import { Pane } from "./Pane";
import { Sidebar } from "./Sidebar";

const PAGE_SIZE = 10;
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
  mouse,
}: {
  work: WorkList;
  runs: CloudRuns;
  chats: PiChats;
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
  const [selected, setSelected] = useState(-1);
  const [notice, setNotice] = useState<string | null>(null);
  const closeGuard = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  const sidebarBox = useRef<DOMElement | null>(null);
  const paneBoxes = useRef(new Map<string, DOMElement>());
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

  const onSubmit = (paneId: string, text: string): void => {
    const pane = layout.workspaces
      .flatMap((w) => panes(w.root))
      .find((candidate) => candidate.id === paneId);
    const current = taskOf(pane?.taskId ?? null);
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
  const selectedIndex = selected < 0 ? firstSelectable(rows) : selected;
  const workspace = activeWorkspace(layout);
  const sidebarFocused = layout.focus === "sidebar";

  const activate = (index: number): void => {
    const row = rows[index];
    if (!row) return;
    setSelected(index);
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
      setLayout((current) => cycleFocus(current, key.shift ? -1 : 1));
      return;
    }
    if (!sidebarFocused) {
      if (key.pageUp) scrollPane(workspace.focusedPaneId, -10);
      if (key.pageDown) scrollPane(workspace.focusedPaneId, 10);
      return;
    }
    if (key.escape) {
      setLayout((current) => focusPane(current, workspace.focusedPaneId));
    } else if (key.downArrow || input === "j") {
      setSelected(moveSelection(rows, selectedIndex, 1));
    } else if (key.upArrow || input === "k") {
      setSelected(moveSelection(rows, selectedIndex, -1));
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
      activate(selectedIndex);
    }
  });

  // Clicking a row opens it like Enter; clicking elsewhere in the sidebar focuses it; clicking a pane focuses that pane.
  const onClick = (click: Click): void => {
    const sidebar = sidebarBox.current && boxOf(sidebarBox.current);
    if (sidebar && hitTest(click, [["sidebar", sidebar]])) {
      const index = click.row - sidebar.top;
      if (moveSelection(rows, index - 1, 1) === index) activate(index);
      else setLayout(focusSidebar);
      return;
    }
    const panes = [...paneBoxes.current].map(
      ([paneId, element]) => [paneId, boxOf(element)] as [string, ScreenBox],
    );
    const hit = hitTest(click, panes);
    if (hit) setLayout((current) => focusPane(current, hit[0]));
  };
  const onWheel = (wheel: Wheel): void => {
    const panes = [...paneBoxes.current].map(
      ([paneId, element]) => [paneId, boxOf(element)] as [string, ScreenBox],
    );
    const hit = hitTest(wheel, panes);
    if (hit) scrollPane(hit[0], wheel.delta * 3);
  };
  // Typing in a focused pane goes to its composer; the app's own keys stay with the app.
  const onKey = (sequence: string): void => {
    if (layout.focus !== "pane" || isAppKey(sequence)) return;
    const paneId = workspace.focusedPaneId;
    const composer = composerFor(paneId);
    const offer = offers.current.get(paneId);
    const key = pickerKey(sequence);
    // With an open offer and nothing typed, arrows and Enter drive the picker.
    if (offer && !dismissed.has(offer.id) && key && composer.isEmpty()) {
      onPick(paneId, offer, key);
      return;
    }
    composer.handleInput(sequence);
  };

  const onPick = (
    paneId: string,
    offer: ActionsLine,
    key: "up" | "down" | "choose" | "dismiss",
  ): void => {
    const index = pickerIndex.get(paneId) ?? 0;
    const last = offer.actions.length - 1;
    if (key === "up" || key === "down") {
      const next = Math.min(last, Math.max(0, index + (key === "up" ? -1 : 1)));
      setPickerIndex((indexes) => new Map(indexes).set(paneId, next));
      return;
    }
    const action = offer.actions[Math.min(index, last)];
    if (key === "choose" && !canRun(action)) return;
    setDismissed((ids) => new Set(ids).add(offer.id));
    if (key === "choose" && action.kind === "compose") {
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

  const renderNode = (
    node: LayoutNode,
    divider: "left" | "top" | null,
  ): ReactElement =>
    node.kind === "pane" ? (
      <Box
        key={node.id}
        ref={(element) => {
          if (element) paneBoxes.current.set(node.id, element);
          else paneBoxes.current.delete(node.id);
        }}
        flexGrow={1}
        flexBasis={0}
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
          focused={!sidebarFocused && node.id === workspace.focusedPaneId}
        />
      </Box>
    ) : (
      <Box
        key={paneIds(node).join()}
        flexDirection={node.direction}
        flexGrow={1}
        flexBasis={0}
        {...dividerProps(divider)}
      >
        {node.children.map((child, index) =>
          renderNode(
            child,
            index === 0 ? null : node.direction === "row" ? "left" : "top",
          ),
        )}
      </Box>
    );

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
      {renderNode(workspace.root, null)}
    </Box>
  );
}
