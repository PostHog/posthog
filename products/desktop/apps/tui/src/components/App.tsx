import type { EventEmitter } from "node:events";
import type { Task } from "@posthog/shared";
import { Box, type DOMElement, measureElement, useApp, useInput } from "ink";
import { type ReactElement, useEffect, useMemo, useRef, useState } from "react";
import {
  activeWorkspace,
  closeFocused,
  cycleFocus,
  focusPane,
  focusSidebar,
  type LayoutNode,
  type LayoutState,
  loadLayout,
  paneIds,
  panes,
  saveLayout,
  splitFocused,
} from "../layout";
import { type Click, hitTest, type Box as ScreenBox } from "../mouse";
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
  clicks,
}: {
  work: WorkList;
  runs: CloudRuns;
  clicks?: EventEmitter<{ click: [Click] }>;
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
  const [selected, setSelected] = useState(-1);
  const [notice, setNotice] = useState<string | null>(null);
  const closeGuard = useRef(new DoublePress(CLOSE_CONFIRM_MS));
  const sidebarBox = useRef<DOMElement | null>(null);
  const paneBoxes = useRef(new Map<string, DOMElement>());

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
  const taskOf = (taskId: string | null): Task | undefined =>
    taskId
      ? (page.tasks?.find((task) => task.id === taskId) ?? known.get(taskId))
      : undefined;

  const rows = useMemo(
    () =>
      sidebarRows({ layout, work: page, collapsed, working: new Set(), known }),
    [layout, page, collapsed, known],
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
    if (shortcut) {
      const direction = shortcut === "splitDown" ? "column" : "row";
      setLayout((current) => splitFocused(current, direction));
      return;
    }
    if (key.tab) {
      setLayout((current) => cycleFocus(current, key.shift ? -1 : 1));
      return;
    }
    if (!sidebarFocused) return;
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
  const onClickRef = useRef(onClick);
  onClickRef.current = onClick;

  useEffect(() => {
    if (!clicks) return;
    const listener = (click: Click): void => onClickRef.current(click);
    clicks.on("click", listener);
    return () => {
      clicks.off("click", listener);
    };
  }, [clicks]);

  const titleOf = (taskId: string | null): string => {
    if (taskId === null) return "New chat";
    return taskOf(taskId)?.title ?? "Loading…";
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
          title={titleOf(node.taskId)}
          task={taskOf(node.taskId)}
          runs={runs}
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
