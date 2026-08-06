import { type RefObject, useEffect, useState } from "react";

export type Orientation = "landscape" | "portrait";

// Reports whether the element is wider than tall, so a matching-orientation
// video can be chosen as the grid resizes.
export function useElementOrientation(
  ref: RefObject<HTMLElement | null>,
): Orientation {
  const [orientation, setOrientation] = useState<Orientation>("landscape");

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (!box || box.width === 0 || box.height === 0) return;
      setOrientation(box.width >= box.height ? "landscape" : "portrait");
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);

  return orientation;
}
