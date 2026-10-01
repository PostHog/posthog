import { useEffect, useRef, useState } from "react";

const NOTICE_MS = 8_000;

export interface Notice {
  notice: string | null;
  // Shows the text for a while; a later notice replaces it and its timer.
  flashNotice: (text: string, ms?: number) => void;
  // Shows the text until the next notice or clear, for work still in progress.
  showNotice: (text: string) => void;
  clearNotice: () => void;
}

// The one-line notice under the sidebar.
export function useNotice(): Notice {
  const [notice, setNotice] = useState<string | null>(null);
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
    notice,
    flashNotice: (text, ms = NOTICE_MS) => {
      cancel();
      setNotice(text);
      timer.current = setTimeout(() => {
        timer.current = null;
        setNotice(null);
      }, ms);
    },
    showNotice: (text) => {
      cancel();
      setNotice(text);
    },
    clearNotice: () => {
      cancel();
      setNotice(null);
    },
  };
}
