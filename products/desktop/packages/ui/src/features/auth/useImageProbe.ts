import { useEffect, useState } from "react";

export type ImageProbeResult = "unknown" | "loaded" | "failed";

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
    const image = new Image();
    image.onload = () => {
      if (!cancelled) setProbe({ result: "loaded", url, loading: false });
    };
    image.onerror = () => {
      if (!cancelled) {
        setProbe({ result: "failed", url: undefined, loading: false });
      }
    };
    image.src = url;
    return () => {
      cancelled = true;
      image.onload = null;
      image.onerror = null;
    };
  }, [url]);

  return probe;
}
