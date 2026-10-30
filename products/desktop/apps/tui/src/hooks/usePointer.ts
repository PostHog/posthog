import { type DOMElement, measureElement } from "ink";
import {
  type Dispatch,
  type RefObject,
  type SetStateAction,
  useRef,
} from "react";
import type { ChatView } from "../chatView";
import { copyToClipboard } from "../clipboard";
import { HEADER_GAP } from "../components/Sidebar";
import type { Composer } from "../composer";
import { focusPane, focusSidebar, type LayoutState } from "../layout";
import {
  type Click,
  hitTest,
  type Box as ScreenBox,
  type Wheel,
} from "../mouse";
import { openImage, openUrl } from "../openUrl";
import { Gesture } from "../selection";
import type { SidebarRow } from "../sidebar";
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
  boxes: ScreenBoxes;
}

// Long enough for the report that comes with a drop, short enough that a pointer moved before a typed paste does not count.
const DROP_REPORT_MS = 200;

// Mouse input: clicks, hover, the wheel, and a drag that selects chat text and copies it on release.
export function usePointer({
  rows,
  activate,
  setNavigating,
  setLayout,
  chatIn,
  chats,
  composerFor,
  scrollPane,
  repaint,
  flashNotice,
}: {
  rows: SidebarRow[];
  activate: (index: number) => void;
  setNavigating: (navigating: boolean) => void;
  setLayout: Dispatch<SetStateAction<LayoutState>>;
  chatIn: (paneId: string) => ChatView;
  chats: () => Iterable<ChatView>;
  composerFor: (paneId: string) => Composer;
  scrollPane: (paneId: string, lines: number) => void;
  repaint: () => void;
  flashNotice: FlashNotice;
}): Pointer {
  const sidebarBox = useRef<DOMElement | null>(null);
  const lastMove = useRef<{ at: Click; time: number } | null>(null);
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
      if (chat.jumpAt(click.row - box.top, click.column - box.left)) {
        repaint();
        return;
      }
      const link = chat.linkAt(click.row - box.top, click.column - box.left);
      const image = chat.imageAt(click.row - box.top);
      if (link) openUrl(link);
      else if (image) openImage(image);
      else if (chat.toggleAt(click.row - box.top)) repaint();
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

  return {
    onPress: (at) => {
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
      if (range) selectIn(range.from, range.to);
    },
    onRelease: (at) => {
      const end = gesture.current.release(at);
      if (end?.kind === "click") onClick(end.at);
      if (end?.kind !== "select" || !selecting.current) return;
      selectIn(end.from, end.to);
      const text = selecting.current.target.selectedText();
      if (!text.trim()) return;
      copyToClipboard(text);
      flashNotice("Copied to clipboard", {
        paneId: selecting.current.paneId,
      });
    },
    onMove: (move) => {
      lastMove.current = { at: move, time: Date.now() };
      let changed = false;
      for (const [paneId, element] of chatBoxes.current) {
        const box = boxOf(element);
        const row = hitTest(move, [["chat", box]]) ? move.row - box.top : null;
        if (chatIn(paneId).hoverAt(row)) changed = true;
      }
      if (changed) repaint();
    },
    onWheel: (wheel) => {
      const paneId = paneHit(wheel);
      if (paneId) scrollPane(paneId, wheel.delta * 3);
    },
    paneAtDrop: () => {
      const move = lastMove.current;
      return move && Date.now() - move.time <= DROP_REPORT_MS
        ? paneHit(move.at)
        : undefined;
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
