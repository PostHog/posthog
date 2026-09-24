import {
  layoutWorkSections,
  type PreferredWorkSectionHeights,
  resizeWorkSections,
  WORK_SECTION_HEADER_HEIGHT,
  type WorkSectionHeights,
  type WorkSectionId,
  type WorkSectionInput,
} from "@posthog/ui/features/canvas/workSectionLayout";
import {
  type KeyboardEvent,
  type PointerEvent,
  type RefCallback,
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

const KEYBOARD_STEP = 16;

export interface WorkSectionResizer {
  onPointerDown: (event: PointerEvent<HTMLElement>) => void;
  onPointerMove: (event: PointerEvent<HTMLElement>) => void;
  onPointerUp: (event: PointerEvent<HTMLElement>) => void;
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  onDoubleClick: () => void;
}

interface DragState {
  upper: WorkSectionId;
  lower: WorkSectionId;
  startY: number;
  heights: WorkSectionHeights;
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
  areaRef: RefCallback<HTMLElement>;
  contentRef: (id: WorkSectionId) => RefCallback<HTMLElement>;
  heights: WorkSectionHeights;
  measured: boolean;
  dragging: WorkSectionId | null;
  resizer: (upper: WorkSectionId, lower: WorkSectionId) => WorkSectionResizer;
} {
  const [areaHeight, setAreaHeight] = useState(0);
  const [contentHeights, setContentHeights] = useState<
    Partial<Record<WorkSectionId, number>>
  >({});
  const [draft, setDraft] = useState<PreferredWorkSectionHeights | null>(null);
  const [dragging, setDragging] = useState<WorkSectionId | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const contentElements = useRef(new Map<WorkSectionId, HTMLElement>());
  const contentObserver = useRef<ResizeObserver | null>(null);
  const areaObserver = useRef<ResizeObserver | null>(null);

  const readContent = useCallback(() => {
    setContentHeights((previous) => {
      let changed = false;
      const next = { ...previous };
      for (const [id, element] of contentElements.current) {
        if (next[id] !== element.offsetHeight) {
          next[id] = element.offsetHeight;
          changed = true;
        }
      }
      return changed ? next : previous;
    });
  }, []);

  useLayoutEffect(() => {
    contentObserver.current = new ResizeObserver(readContent);
    for (const element of contentElements.current.values()) {
      contentObserver.current.observe(element);
    }
    return () => {
      contentObserver.current?.disconnect();
      contentObserver.current = null;
      areaObserver.current?.disconnect();
      areaObserver.current = null;
    };
  }, [readContent]);

  const areaRef = useCallback<RefCallback<HTMLElement>>((element) => {
    areaObserver.current?.disconnect();
    areaObserver.current = null;
    if (!element) return;
    const observer = new ResizeObserver(() =>
      setAreaHeight(element.clientHeight),
    );
    observer.observe(element);
    areaObserver.current = observer;
    setAreaHeight(element.clientHeight);
  }, []);

  const contentRefs = useRef(
    new Map<WorkSectionId, RefCallback<HTMLElement>>(),
  );
  const contentRef = useCallback(
    (id: WorkSectionId): RefCallback<HTMLElement> => {
      const existing = contentRefs.current.get(id);
      if (existing) return existing;
      const ref: RefCallback<HTMLElement> = (element) => {
        const previous = contentElements.current.get(id);
        if (previous) contentObserver.current?.unobserve(previous);
        if (element) {
          contentElements.current.set(id, element);
          contentObserver.current?.observe(element);
        } else {
          contentElements.current.delete(id);
        }
        readContent();
      };
      contentRefs.current.set(id, ref);
      return ref;
    },
    [readContent],
  );

  const inputs = useMemo<WorkSectionInput[]>(
    () =>
      sections.map((section) => ({
        id: section.id,
        open: section.open,
        contentHeight: contentHeights[section.id] ?? 0,
      })),
    [sections, contentHeights],
  );
  const effective = draft ?? preferred;
  const available = areaHeight - WORK_SECTION_HEADER_HEIGHT * sections.length;
  const heights = useMemo(
    () => layoutWorkSections(inputs, available, effective),
    [inputs, available, effective],
  );
  const measured =
    areaHeight > 0 &&
    sections.every(
      (section) => !section.open || contentHeights[section.id] !== undefined,
    );

  const heightsRef = useRef(heights);
  heightsRef.current = heights;
  const inputsRef = useRef(inputs);
  inputsRef.current = inputs;
  const preferredRef = useRef(preferred);
  preferredRef.current = preferred;

  const resizer = useCallback(
    (upper: WorkSectionId, lower: WorkSectionId): WorkSectionResizer => {
      const resizeBy = (
        delta: number,
        base: WorkSectionHeights,
      ): PreferredWorkSectionHeights =>
        resizeWorkSections({
          sections: inputsRef.current,
          heights: base,
          upper,
          lower,
          delta,
          preferred: preferredRef.current,
        });
      return {
        onPointerDown: (event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          event.currentTarget.setPointerCapture(event.pointerId);
          dragRef.current = {
            upper,
            lower,
            startY: event.clientY,
            heights: heightsRef.current,
          };
          setDraft(preferredRef.current);
          setDragging(lower);
        },
        onPointerMove: (event) => {
          const drag = dragRef.current;
          if (!drag) return;
          setDraft(resizeBy(event.clientY - drag.startY, drag.heights));
        },
        onPointerUp: (event) => {
          const drag = dragRef.current;
          if (!drag) return;
          if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
          }
          dragRef.current = null;
          onPreferredChange(
            resizeBy(event.clientY - drag.startY, drag.heights),
          );
          setDraft(null);
          setDragging(null);
        },
        onKeyDown: (event) => {
          if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
          event.preventDefault();
          const step = event.key === "ArrowUp" ? -KEYBOARD_STEP : KEYBOARD_STEP;
          onPreferredChange(resizeBy(step, heightsRef.current));
        },
        onDoubleClick: () => onPreferredChange({}),
      };
    },
    [onPreferredChange],
  );

  return {
    areaRef,
    contentRef,
    heights,
    measured,
    dragging,
    resizer,
  };
}
