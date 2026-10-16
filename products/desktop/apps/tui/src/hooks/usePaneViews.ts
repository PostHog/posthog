import type { ImageContent } from "@earendil-works/pi-ai";
import { useRef, useState } from "react";
import { ChatView } from "../chatView";
import { Composer } from "../composer";
import { findPane, type LayoutState } from "../layout";
import type { TranscriptLine } from "../transcript";

export interface PaneViews {
  // Keyed by pane and task, so a pane that switches task starts that chat at its latest message.
  chatFor: (paneId: string, taskId: string | null) => ChatView;
  // The chat the pane shows now.
  chatIn: (paneId: string) => ChatView;
  chats: () => Iterable<ChatView>;
  composerFor: (paneId: string) => Composer;
  scrollPane: (paneId: string, lines: number) => void;
  // Each pane's transcript as last drawn.
  linesOf: (paneId: string) => TranscriptLine[];
  setLines: (paneId: string, lines: TranscriptLine[]) => void;
  // Scrolling, selection and typing happen inside pi-tui components, so a tick tells React to draw again.
  repaint: () => void;
}

// The pi-tui chat views and composers each pane draws, kept across renders.
export function usePaneViews({
  layout,
  onSubmit,
}: {
  layout: LayoutState;
  onSubmit: (paneId: string, text: string, images: ImageContent[]) => void;
}): PaneViews {
  const chatViews = useRef(new Map<string, ChatView>());
  const composers = useRef(new Map<string, Composer>());
  const paneLines = useRef(new Map<string, TranscriptLine[]>());
  const [, setTick] = useState(0);
  const repaint = (): void => setTick((tick) => tick + 1);
  const chatFor = (paneId: string, taskId: string | null): ChatView => {
    const key = `${paneId}:${taskId}`;
    let chat = chatViews.current.get(key);
    if (!chat) {
      chat = new ChatView();
      chatViews.current.set(key, chat);
    }
    return chat;
  };
  const chatIn = (paneId: string): ChatView =>
    chatFor(paneId, findPane(layout, paneId)?.taskId ?? null);
  return {
    chatFor,
    chatIn,
    chats: () => chatViews.current.values(),
    composerFor: (paneId) => {
      let composer = composers.current.get(paneId);
      if (!composer) {
        composer = new Composer(repaint, (text, images) =>
          onSubmit(paneId, text, images),
        );
        composers.current.set(paneId, composer);
      }
      return composer;
    },
    scrollPane: (paneId, lines) => {
      chatIn(paneId).scrollBy(lines);
      repaint();
    },
    linesOf: (paneId) => paneLines.current.get(paneId) ?? [],
    setLines: (paneId, lines) => paneLines.current.set(paneId, lines),
    repaint,
  };
}
