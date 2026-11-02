import { useEffect, useRef, useState } from "react";
import { track } from "../analytics";

const NOTICE_MS = 8_000;

// Where a notice belongs: a pane, or any pane showing a chat. A notice with neither is about the app.
export interface NoticePlace {
  paneId?: string | null;
  taskId?: string | null;
}

export interface ShownNotice extends NoticePlace {
  text: string;
}

export interface Notice {
  // The notice showing now. One placed in a chat shows above that chat's composer; others show under the sidebar.
  shown: ShownNotice | null;
  // Shows the text for a while; a later notice replaces it and its timer.
  flashNotice: (text: string, options?: NoticePlace & { ms?: number }) => void;
  // Shows the text until the next notice or clear, for work still in progress.
  showNotice: (text: string, place?: NoticePlace) => void;
  clearNotice: () => void;
}

export type FlashNotice = Notice["flashNotice"];

// Notices are where the TUI tells the user something went wrong, so each one is an event with its text.
const noticeShown = (text: string, place: NoticePlace): void =>
  track("notice shown", {
    text: text.slice(0, 200),
    failure: /^couldn't|failed|cannot|sign in/i.test(text),
    pane_id: place.paneId ?? null,
    task_id: place.taskId ?? null,
  });

export function useNotice(): Notice {
  const [shown, setShown] = useState<ShownNotice | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cancel = (): void => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  return {
    shown,
    flashNotice: (text, { ms = NOTICE_MS, ...place } = {}) => {
      cancel();
      noticeShown(text, place);
      setShown({ text, ...place });
      timer.current = setTimeout(() => {
        timer.current = null;
        setShown(null);
      }, ms);
    },
    showNotice: (text, place = {}) => {
      cancel();
      noticeShown(text, place);
      setShown({ text, ...place });
    },
    clearNotice: () => {
      cancel();
      setShown(null);
    },
  };
}

// Whether a notice belongs above this pane's composer.
export const noticeIn = (
  notice: ShownNotice | null,
  paneId: string,
  taskId: string | null,
): boolean =>
  Boolean(notice) &&
  (notice?.paneId === paneId ||
    (Boolean(notice?.taskId) && notice?.taskId === taskId));
