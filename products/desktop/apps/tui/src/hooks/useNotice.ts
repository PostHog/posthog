import { useEffect, useRef, useState } from "react";

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
      setShown({ text, ...place });
      timer.current = setTimeout(() => {
        timer.current = null;
        setShown(null);
      }, ms);
    },
    showNotice: (text, place = {}) => {
      cancel();
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
