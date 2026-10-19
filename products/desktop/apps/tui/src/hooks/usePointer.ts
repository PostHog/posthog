import { type DOMElement, measureElement } from "ink";
import {
  type Dispatch,
  type RefObject,
  type SetStateAction,
  useRef,
} from "react";
import { track } from "../analytics";
import type { ChatView } from "../chatView";
import { copyToClipboard } from "../clipboard";
import { ALL_TAB_COLUMN, HEADER_GAP } from "../components/Sidebar";
import type { Composer } from "../composer";
import { focusPane, focusSidebar, type LayoutState } from "../layout";
import {
  type Click,
  hitTest,
  type Box as ScreenBox,
  type Wheel,
} from "../mouse";
import { openImage, openUrl } from "../openUrl";
import type { ChatScope } from "../prefs";
import { Gesture } from "../selection";
import { isSelectable, type SidebarRow } from "../sidebar";
import type { FlashNotice } from "./useNotice";

function boxOf(element: DOMElement): ScreenBox {
  const { x, y, width, height } = measureElement(element);
  return { left: x + 1, top: y + 1, right: x + width, bottom: y + height };
}

// Where things sit on screen, reported by the elements as they mount, so a click can be matched to them.
export interface ScreenBoxes {
  sidebar: RefObject<DOMElement | null>;
  setPane: (paneId: string, element: DOMElement | null) => void;
  setChat: (paneId: string, element: DOMElement | null) => void;
  setComposer: (paneId: string, element: DOMElement | null) => void;
  setPrChip: (
    paneId: string,
    element: DOMElement | null,
    url: string | null,
  ) => void;
}

export interface Pointer {
  onPress: (at: Click) => void;
  onDrag: (at: Click) => void;
  onRelease: (at: Click) => void;
  onMove: (at: Click) => void;
  onWheel: (at: Wheel) => void;
  // The pane a file was just dropped on: Ghostty reports the pointer a few milliseconds before it pastes the path.
  paneAtDrop: () => string | undefined;
  // A key was typed: the pointer's last report no longer says where a paste belongs.
  typed: () => void;
  boxes: ScreenBoxes;
}

// How often a drag held above or below a chat scrolls it a line.
const EDGE_SCROLL_MS = 50;

// Mouse input: clicks, hover, the wheel, and a drag that selects chat text and copies it on release.
export function usePointer({
  rows,
  activate,
  navigate,
  setNavigating,
  setCollapsed,
  setScope,
  setLayout,
  chatIn,
  chats,
  composerFor,
  scrollPane,
  repaint,
  flashNotice,
  todayAt = () => false,
}: {
  rows: SidebarRow[];
  activate: (index: number) => void;
  // The wheel over the sidebar walks its chats, as the arrow keys do.
  navigate: (step: 1 | -1) => void;
  setNavigating: (navigating: boolean) => void;
  setCollapsed: (workspaceId: string, collapsed: boolean) => void;
  setScope: (scope: ChatScope) => void;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  chatIn: (paneId: string) => ChatView;
  chats: () => Iterable<ChatView>;
  composerFor: (paneId: string) => Composer;
  scrollPane: (paneId: string, lines: number) => void;
  repaint: () => void;
  flashNotice: FlashNotice;
  // A click on the Today briefing in a pane, by cell within its chat area; true when it hit a link.
  todayAt?: (paneId: string, row: number, column: number) => boolean;
}): Pointer {
  const sidebarBox = useRef<DOMElement | null>(null);
  const lastMove = useRef<Click | null>(null);
  const paneBoxes = useRef(new Map<string, DOMElement>());
  const chatBoxes = useRef(new Map<string, DOMElement>());
  const composerBoxes = useRef(new Map<string, DOMElement>());
  const prChips = useRef(
    new Map<string, { element: DOMElement; url: string }>(),
  );
  const paneHit = (at: Click): string | undefined =>
    hitTest(
      at,
      [...paneBoxes.current].map(
        ([paneId, element]) => [paneId, boxOf(element)] as [string, ScreenBox],
      ),
    )?.[0];

  // Clicking a row opens it like Enter; clicking elsewhere in the sidebar focuses it; clicking a pane focuses that pane.
  const onClick = (click: Click): void => {
    const sidebar = sidebarBox.current && boxOf(sidebarBox.current);
    if (sidebar && hitTest(click, [["sidebar", sidebar]])) {
      const onScreen = click.row - sidebar.top;
      const index = onScreen === 0 ? 0 : Math.max(0, onScreen - HEADER_GAP);
      const row = rows[index];
      // A click on a workspace's title folds it, or opens it, which unfolds it; one on a chat opens the chat.
      if (row?.kind === "workspace" && row.expanded) {
        setCollapsed(row.workspaceId, true);
      } else if (row?.kind === "tabs") {
        setScope(
          click.column - sidebar.left >= ALL_TAB_COLUMN ? "all" : "mine",
        );
      } else if (row && isSelectable(row)) {
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
    const paneId = paneHit(click);
    if (paneId) {
      setNavigating(false);
      setLayout((current) => focusPane(current, paneId));
      const chatBox = chatBoxes.current.get(paneId);
      const box = chatBox && boxOf(chatBox);
      const chat = chatIn(paneId);
      const composerBox = composerBoxes.current.get(paneId);
      const composerAt = composerBox && boxOf(composerBox);
      if (composerAt && hitTest(click, [["composer", composerAt]])) {
        composerFor(paneId).placeCursor({
          row: click.row - composerAt.top,
          column: click.column - composerAt.left,
        });
        return;
      }
      if (!box || !hitTest(click, [["chat", box]])) return;
      if (todayAt(paneId, click.row - box.top, click.column - box.left)) return;
      if (chat.jumpAt(click.row - box.top, click.column - box.left)) {
        repaint();
        return;
      }
      const link = chat.linkAt(click.row - box.top, click.column - box.left);
      const image = chat.imageAt(click.row - box.top);
      if (link) {
        track("link opened", { pane_id: paneId });
        openUrl(link);
      } else if (image) {
        track("image opened", { pane_id: paneId });
        openImage(image);
      } else if (chat.toggleAt(click.row - box.top)) {
        track("tool group toggled", { pane_id: paneId });
        repaint();
      }
    }
  };

  // A press starts a click or, once the pointer moves, a selection in the chat it landed on.
  const gesture = useRef(new Gesture());
  // A drag selects in the chat or the composer it started in; either one copies its text on release.
  const selecting = useRef<{
    target: ChatView | Composer;
    box: ScreenBox;
    paneId: string;
  } | null>(null);
  const selectIn = (from: Click, to: Click): void => {
    const current = selecting.current;
    if (!current) return;
    const local = (at: Click): Click => ({
      row: at.row - current.box.top,
      column: at.column - current.box.left,
    });
    current.target.select(local(from), local(to));
    repaint();
  };
  // The drag in progress, so a scroll mid-drag can move the selection's end to where the pointer is.
  const drag = useRef<{ from: Click; to: Click } | null>(null);
  const edgeScroll = useRef<ReturnType<typeof setInterval> | null>(null);
  const stopDrag = (): void => {
    if (edgeScroll.current) clearInterval(edgeScroll.current);
    edgeScroll.current = null;
    drag.current = null;
  };

  return {
    onPress: (at) => {
      stopDrag();
      gesture.current.press(at);
      for (const chat of chats()) chat.clearSelection();
      for (const paneId of composerBoxes.current.keys())
        composerFor(paneId).clearSelection();
      selecting.current = null;
      for (const [paneId, element] of chatBoxes.current) {
        const box = boxOf(element);
        if (hitTest(at, [["chat", box]]))
          selecting.current = { target: chatIn(paneId), box, paneId };
      }
      for (const [paneId, element] of composerBoxes.current) {
        const box = boxOf(element);
        if (hitTest(at, [["composer", box]]))
          selecting.current = { target: composerFor(paneId), box, paneId };
      }
      repaint();
    },
    onDrag: (at) => {
      const range = gesture.current.drag(at);
      if (!range) return;
      drag.current = range;
      selectIn(range.from, range.to);
      const current = selecting.current;
      const outside =
        current !== null &&
        current.target === chatIn(current.paneId) &&
        (at.row < current.box.top || at.row > current.box.bottom);
      if (!outside) {
        if (edgeScroll.current) clearInterval(edgeScroll.current);
        edgeScroll.current = null;
      } else if (!edgeScroll.current) {
        edgeScroll.current = setInterval(() => {
          const held = drag.current;
          const target = selecting.current;
          if (!held || !target) return;
          scrollPane(target.paneId, held.to.row < target.box.top ? -1 : 1);
          selectIn(held.from, held.to);
        }, EDGE_SCROLL_MS);
      }
    },
    onRelease: (at) => {
      stopDrag();
      const end = gesture.current.release(at);
      if (end?.kind === "click") onClick(end.at);
      const current = selecting.current;
      if (!current || !end || end.kind === "click") return;
      if (end.kind === "select") selectIn(end.from, end.to);
      else {
        const { box, target } = current;
        const local = { row: at.row - box.top, column: at.column - box.left };
        if (!target.selectWordAt(local)) return;
        repaint();
      }
      const text = current.target.selectedText();
      if (!text.trim()) return;
      track("text copied", {
        via: end.kind === "word" ? "double click" : "drag",
        from: current.target === chatIn(current.paneId) ? "chat" : "composer",
        chars: text.length,
        pane_id: current.paneId,
      });
      copyToClipboard(text);
      flashNotice("Copied to clipboard", { paneId: current.paneId });
    },
    onMove: (move) => {
      lastMove.current = move;
      let changed = false;
      for (const [paneId, element] of chatBoxes.current) {
        const box = boxOf(element);
        const row = hitTest(move, [["chat", box]]) ? move.row - box.top : null;
        if (chatIn(paneId).hoverAt(row)) changed = true;
      }
      if (changed) repaint();
    },
    onWheel: (wheel) => {
      const sidebar = sidebarBox.current && boxOf(sidebarBox.current);
      if (sidebar && hitTest(wheel, [["sidebar", sidebar]])) {
        navigate(wheel.delta);
        return;
      }
      const paneId = paneHit(wheel);
      if (!paneId) return;
      scrollPane(paneId, wheel.delta * 3);
      const held = drag.current;
      if (held && selecting.current?.paneId === paneId)
        selectIn(held.from, held.to);
    },
    // A drop pastes the file paths with no position, so it lands under the pointer's last report. The terminal
    // reports motion only as the pointer crosses cells, so a long hover before the drop still counts; a key typed
    // since the move does not, so a typed paste of a path stays in the focused pane.
    paneAtDrop: () => {
      const move = lastMove.current;
      return move ? paneHit(move) : undefined;
    },
    typed: () => {
      lastMove.current = null;
    },
    boxes: {
      sidebar: sidebarBox,
      setPane: (paneId, element) => {
        if (element) paneBoxes.current.set(paneId, element);
        else paneBoxes.current.delete(paneId);
      },
      setChat: (paneId, element) => {
        if (element) chatBoxes.current.set(paneId, element);
        else chatBoxes.current.delete(paneId);
      },
      setComposer: (paneId, element) => {
        if (element) composerBoxes.current.set(paneId, element);
        else composerBoxes.current.delete(paneId);
      },
      setPrChip: (paneId, element, url) => {
        if (element && url) prChips.current.set(paneId, { element, url });
        else prChips.current.delete(paneId);
      },
    },
  };
}
