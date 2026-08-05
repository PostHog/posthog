import * as Clipboard from "expo-clipboard";
import { useCallback, useEffect, useRef, useState } from "react";

export function useCopy(resetMs = 2000): {
  copied: boolean;
  copy: (text: string, onSuccess?: () => void) => void;
} {
  const [copied, setCopied] = useState(false);
  const timeout = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => () => clearTimeout(timeout.current), []);

  const copy = useCallback(
    (text: string, onSuccess?: () => void) => {
      Clipboard.setStringAsync(text).then(
        () => {
          setCopied(true);
          clearTimeout(timeout.current);
          timeout.current = setTimeout(() => setCopied(false), resetMs);
          onSuccess?.();
        },
        () => {},
      );
    },
    [resetMs],
  );

  return { copied, copy };
}
