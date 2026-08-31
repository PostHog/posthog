import { useEffect, useState } from "react";
import { Image } from "react-native";
import type { ImageProbeResult } from "./gravatar";

export interface ImageProbe {
  result: ImageProbeResult;
  url: string | undefined;
  loading: boolean;
}

const INITIAL_PROBE: ImageProbe = {
  result: "unknown",
  url: undefined,
  loading: false,
};

export function useImageProbe(url: string | undefined): ImageProbe {
  const [probe, setProbe] = useState<ImageProbe>(INITIAL_PROBE);

  useEffect(() => {
    if (!url) {
      setProbe(INITIAL_PROBE);
      return;
    }
    let cancelled = false;
    setProbe((previous) => ({ ...previous, loading: true }));
    Image.prefetch(url)
      .then((ok) => {
        if (cancelled) return;
        if (ok) {
          setProbe({ result: "loaded", url, loading: false });
        } else {
          setProbe({ result: "failed", url: undefined, loading: false });
        }
      })
      .catch(() => {
        if (!cancelled) {
          setProbe({ result: "failed", url: undefined, loading: false });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [url]);

  return probe;
}
