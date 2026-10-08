import type { Task } from "@posthog/shared";
import { type Dispatch, type SetStateAction, useMemo, useState } from "react";
import { focusSidebar, type LayoutState } from "../layout";
import type { LocalAgent } from "../local";
import {
  activateRow,
  cursorIndex,
  moveSelection,
  type SidebarRow,
  selectionKey,
  sidebarRows,
  type WorkPage,
} from "../sidebar";

export interface SidebarState {
  rows: SidebarRow[];
  selectedIndex: number;
  // Arrows keep walking the sidebar after it hands focus to a chat, until a pane is clicked.
  navigating: boolean;
  setNavigating: (navigating: boolean) => void;
  // Opens the row like Enter: a chat, a workspace, or the next page.
  activate: (index: number) => void;
  // Moves the sidebar cursor and hands focus to that chat, so typing goes straight to it.
  navigate: (step: 1 | -1) => void;
  setCollapsed: (workspaceId: string, collapsed: boolean) => void;
}

export function useSidebar({
  layout,
  setLayout,
  page,
  known,
  fresh,
  signedIn,
  localActive,
  localSessions,
  loadMore,
  working,
  waiting,
  titles,
}: {
  layout: LayoutState;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  page: WorkPage;
  known: Map<string, Task>;
  fresh: Map<string, Task>;
  signedIn: boolean;
  localActive: Map<string, number>;
  localSessions: Map<string, LocalAgent>;
  loadMore: () => void;
  working: Set<string>;
  waiting: Set<string>;
  titles: Map<string, string>;
}): SidebarState {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  // The cursor follows a row's identity, since previewing a chat can move rows.
  const [selected, setSelected] = useState<string | null>(null);
  const [navigating, setNavigating] = useState(false);
  const rows = useMemo(
    () =>
      sidebarRows({
        layout,
        work: page,
        collapsed,
        working,
        waiting,
        known: new Map([...known, ...fresh]),
        titles,
        signedIn,
        local: { active: localActive, running: new Set(localSessions.keys()) },
      }),
    [
      layout,
      page,
      collapsed,
      known,
      fresh,
      signedIn,
      localActive,
      localSessions,
      working,
      waiting,
      titles,
    ],
  );
  const selectedIndex = cursorIndex(rows, selected);
  return {
    rows,
    selectedIndex,
    navigating,
    setNavigating,
    activate: (index) => {
      const row = rows[index];
      if (!row) return;
      setSelected(selectionKey(row));
      const next = activateRow(layout, row);
      if (next === "viewMore") {
        loadMore();
      } else {
        setLayout(next);
      }
    },
    navigate: (step) => {
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
    },
    setCollapsed: (workspaceId, collapse) =>
      setCollapsed((current) => {
        const next = new Set(current);
        if (collapse) next.add(workspaceId);
        else next.delete(workspaceId);
        return next;
      }),
  };
}
