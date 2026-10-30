import { Box, useInput } from "ink";
import { type ReactElement, useEffect, useMemo, useState } from "react";
import {
  activeWorkspace,
  cycleFocus,
  focusPane,
  type LayoutNode,
  type LayoutState,
  loadLayout,
  paneIds,
  saveLayout,
  splitFocused,
} from "../layout";
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

export function App({ work }: { work: WorkList }): ReactElement {
  const [layout, setLayout] = useState<LayoutState>(loadLayout);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [page, setPage] = useState<WorkPage>({
    tasks: null,
    hasMore: false,
    loadingMore: false,
    error: null,
  });
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState(-1);

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
              error: String(error),
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

  const rows = useMemo(
    () => sidebarRows({ layout, work: page, collapsed, working: new Set() }),
    [layout, page, collapsed],
  );
  const selectedIndex = selected < 0 ? firstSelectable(rows) : selected;
  const workspace = activeWorkspace(layout);
  const sidebarFocused = layout.focus === "sidebar";

  useInput((input, key) => {
    if (key.tab) {
      setLayout((current) => cycleFocus(current, key.shift ? -1 : 1));
      return;
    }
    if (key.ctrl && input === "s") {
      setLayout((current) => splitFocused(current, "row"));
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
      const next = activateRow(layout, rows[selectedIndex]);
      if (next === "viewMore") {
        setPage((current) => ({ ...current, loadingMore: true }));
        setLimit((current) => current + PAGE_SIZE);
      } else {
        setLayout(next);
      }
    }
  });

  const titleOf = (taskId: string | null): string => {
    if (taskId === null) return "New chat";
    return page.tasks?.find((task) => task.id === taskId)?.title ?? "Loading…";
  };

  const renderNode = (
    node: LayoutNode,
    divider: "left" | "top" | null,
  ): ReactElement =>
    node.kind === "pane" ? (
      <Box key={node.id} flexGrow={1} flexBasis={0} {...dividerProps(divider)}>
        <Pane
          title={titleOf(node.taskId)}
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
        rows={rows}
        focused={sidebarFocused}
        selectedIndex={selectedIndex}
        activePaneId={workspace.focusedPaneId}
      />
      {renderNode(workspace.root, null)}
    </Box>
  );
}
