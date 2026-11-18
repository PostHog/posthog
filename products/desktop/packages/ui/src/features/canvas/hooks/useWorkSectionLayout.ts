import {
  layoutWorkSections,
  type PreferredWorkSectionHeights,
  resizeWorkSections,
  WORK_SECTION_HEADER_HEIGHT,
  type WorkSectionHeights,
  type WorkSectionId,
} from "@posthog/ui/features/canvas/workSectionLayout";
import {
  type KeyboardEvent,
  type PointerEvent,
  type RefCallback,
  useMemo,
  useState,
} from "react";

const KEYBOARD_STEP = 16;

type MeasuredKey = WorkSectionId | "area";

export interface WorkSectionResizer {
  onPointerDown: (event: PointerEvent<HTMLElement>) => void;
  onPointerMove: (event: PointerEvent<HTMLElement>) => void;
  onPointerUp: (event: PointerEvent<HTMLElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  onDoubleClick: () => void;
}

interface Drag {
  lower: WorkSectionId;
  startY: number;
  start: WorkSectionHeights;
  preferred: PreferredWorkSectionHeights;
}

function useMeasuredHeights(): {
  measuredHeights: Partial<Record<MeasuredKey, number>>;
  measureRefs: Record<MeasuredKey, RefCallback<HTMLElement>>;
} {
  const [measuredHeights, setMeasuredHeights] = useState<
    Partial<Record<MeasuredKey, number>>
  >({});
  const measureRefs = useMemo(() => {
    const elements = new Map<MeasuredKey, HTMLElement>();
    const measure = () =>
      setMeasuredHeights((previous) => {
        const next = { ...previous };
        for (const [key, element] of elements) {
          next[key] =
            key === "area" ? element.clientHeight : element.offsetHeight;
        }
        return Object.entries(next).every(
          ([key, value]) => previous[key as MeasuredKey] === value,
        )
          ? previous
          : next;
      });
    const observer = new ResizeObserver(measure);
    const ref =
      (key: MeasuredKey): RefCallback<HTMLElement> =>
      (element) => {
        if (!element) return;
        elements.set(key, element);
        observer.observe(element);
        measure();
        return () => {
          observer.unobserve(element);
          elements.delete(key);
        };
      };
    return {
      area: ref("area"),
      pinned: ref("pinned"),
      recent: ref("recent"),
      spaces: ref("spaces"),
    };
  }, []);
  return { measuredHeights, measureRefs };
}

export function useWorkSectionLayout({
  sections,
  preferred,
  onPreferredChange,
}: {
  sections: readonly { id: WorkSectionId; open: boolean }[];
  preferred: PreferredWorkSectionHeights;
  onPreferredChange: (heights: PreferredWorkSectionHeights) => void;
}): {
  measureRefs: Record<MeasuredKey, RefCallback<HTMLElement>>;
  heights: WorkSectionHeights;
  measured: boolean;
  dragging: WorkSectionId | null;
  resizer: (upper: WorkSectionId, lower: WorkSectionId) => WorkSectionResizer;
} {
  const { measuredHeights, measureRefs } = useMeasuredHeights();
  const [drag, setDrag] = useState<Drag | null>(null);

  const areaHeight = measuredHeights.area ?? 0;
  const inputs = sections.map((section) => ({
    ...section,
    contentHeight: measuredHeights[section.id] ?? 0,
  }));
  const heights = layoutWorkSections(
    inputs,
    areaHeight - WORK_SECTION_HEADER_HEIGHT * sections.length,
    drag?.preferred ?? preferred,
  );
  const measured =
    areaHeight > 0 &&
    sections.every(
      (section) => !section.open || measuredHeights[section.id] !== undefined,
    );

  const resizer = (
    upper: WorkSectionId,
    lower: WorkSectionId,
  ): WorkSectionResizer => {
    const resize = (delta: number, base: WorkSectionHeights) =>
      resizeWorkSections({
        sections: inputs,
        heights: base,
        upper,
        lower,
        delta,
        preferred,
      });
    const active = drag?.lower === lower ? drag : null;
    return {
      onPointerDown: (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        setDrag({ lower, startY: event.clientY, start: heights, preferred });
      },
      onPointerMove: (event) => {
        if (!active) return;
        setDrag({
          ...active,
          preferred: resize(event.clientY - active.startY, active.start),
        });
      },
      onPointerUp: (event) => {
        if (!active) return;
        onPreferredChange(resize(event.clientY - active.startY, active.start));
        setDrag(null);
      },
      onKeyDown: (event) => {
        if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
        event.preventDefault();
        onPreferredChange(
          resize(
            event.key === "ArrowUp" ? -KEYBOARD_STEP : KEYBOARD_STEP,
            heights,
          ),
        );
      },
      onDoubleClick: () => onPreferredChange({}),
    };
  };

  return {
    measureRefs,
    heights,
    measured,
    dragging: drag?.lower ?? null,
    resizer,
  };
}
