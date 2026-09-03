import {
  type BoardPaneRect,
  type BoardPoint,
  screenToWorld,
} from "@posthog/core/canvas-v2/boardGeometry";
import {
  type CanvasV2Op,
  type CanvasV2Snapshot,
  type CanvasV2Theme,
  type CanvasV2Viewport,
  findFreeSpot,
  maxZ,
} from "@posthog/shared";
import { BOARD_FRAME_TITLE } from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { DropCaptureLayer } from "@posthog/ui/features/canvas-v2/components/DropCaptureLayer";
import type { FragmentLastEdit } from "@posthog/ui/features/canvas-v2/components/FragmentOverlay";
import { OverlayLayer } from "@posthog/ui/features/canvas-v2/components/OverlayLayer";
import {
  useBoardHighlightedIds,
  useBoardSelectedId,
  useBoardViewStore,
} from "@posthog/ui/features/canvas-v2/interaction/boardViewStore";
import { useBoardPointer } from "@posthog/ui/features/canvas-v2/interaction/useBoardPointer";
import {
  type BoardFrameHandle,
  useBoardFrame,
} from "@posthog/ui/features/canvas-v2/runtime/useBoardFrame";
import type { QueryClient } from "@tanstack/react-query";
import {
  type ReactElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

export interface BoardStageProps {
  boardId: string;
  /** Owned by the caller, so the toolbar and the keyboard can measure the pane. */
  paneRef: React.RefObject<HTMLDivElement | null>;
  snapshot: CanvasV2Snapshot;
  viewport: CanvasV2Viewport;
  setViewport: (viewport: CanvasV2Viewport) => void;
  applyLocal: (ops: CanvasV2Op[]) => void;
  theme: CanvasV2Theme;
  queryClient: QueryClient;
  fragmentErrors: Record<string, string>;
  onFragmentError: (id: string, message: string | null) => void;
  /** Who last changed each fragment, computed by the caller from the log. */
  lastEdits: Record<string, FragmentLastEdit>;
  onEditFragment: (id: string) => void;
  /** True while a library drag runs, so drops land on the board and not the frame. */
  dragActive: boolean;
  onDropFragment: (name: string, world: BoardPoint) => void;
}

/** The board frame with its chrome above it. */
export function BoardStage({
  boardId,
  paneRef,
  snapshot,
  viewport,
  setViewport,
  applyLocal,
  theme,
  queryClient,
  fragmentErrors,
  onFragmentError,
  lastEdits,
  onEditFragment,
  dragActive,
  onDropFragment,
}: BoardStageProps): ReactElement {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [paneRect, setPaneRect] = useState<BoardPaneRect>({
    left: 0,
    top: 0,
    width: 0,
    height: 0,
  });

  const selectedId = useBoardSelectedId();
  const highlightedIds = useBoardHighlightedIds();
  const setSelectedId = useBoardViewStore((state) => state.setSelectedId);

  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;
  const viewportRef = useRef(viewport);
  viewportRef.current = viewport;
  const getSnapshot = useCallback(
    (): CanvasV2Snapshot => snapshotRef.current,
    [],
  );

  const pointer = useBoardPointer({
    paneRef,
    viewport,
    setViewport,
    getSnapshot,
    applyLocal,
    onSelect: setSelectedId,
  });

  // A host drag must not let the frame swallow the pointer stream halfway
  // through. A pan is different: the frame relays that stream, so the frame
  // must stay live or the release never arrives.
  const gestureActive =
    pointer.gesture.kind === "move" || pointer.gesture.kind === "resize";

  const syncedSnapshot = useRef<CanvasV2Snapshot | null>(null);
  const frameRef = useRef<BoardFrameHandle | null>(null);
  const frame = useBoardFrame({
    boardId,
    iframeRef,
    theme,
    queryClient,
    getSnapshot,
    applyLocal,
    events: {
      onReady: () => {
        syncedSnapshot.current = snapshotRef.current;
        frameRef.current?.sendInit(viewportRef.current);
      },
      onFragmentRendered: (id) => onFragmentError(id, null),
      onFragmentError: (id, message) => onFragmentError(id, message),
      onStateChanged: (key, value) =>
        applyLocal([{ type: "set_state", key, value }]),
      onWheel: pointer.onFrameWheel,
      onBackgroundPointer: pointer.onFrameBackgroundPointer,
      onFragmentPointerDown: setSelectedId,
    },
  });
  frameRef.current = frame;

  const { ready, srcDoc, syncSnapshot, setSelection } = frame;
  const setFrameViewport = frame.setViewport;

  useEffect(() => {
    if (!ready) return;
    syncSnapshot(syncedSnapshot.current, snapshot);
    syncedSnapshot.current = snapshot;
  }, [ready, syncSnapshot, snapshot]);

  useEffect(() => {
    setFrameViewport(viewport);
  }, [setFrameViewport, viewport]);

  useEffect(() => {
    setSelection(selectedId);
  }, [setSelection, selectedId]);

  useEffect(() => {
    const pane = paneRef.current;
    if (!pane) return;
    const measure = (): void => {
      const rect = pane.getBoundingClientRect();
      setPaneRect({
        left: rect.left,
        top: rect.top,
        width: rect.width,
        height: rect.height,
      });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(pane);
    window.addEventListener("scroll", measure, true);
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", measure, true);
    };
  }, [paneRef]);

  const bringToFront = useCallback(
    (id: string): void => {
      applyLocal([{ type: "bring_to_front", id }]);
    },
    [applyLocal],
  );

  const removeFragment = useCallback(
    (id: string): void => {
      applyLocal([{ type: "remove_fragment", id }]);
      setSelectedId(null);
    },
    [applyLocal, setSelectedId],
  );

  const duplicateFragment = useCallback(
    (id: string): void => {
      const current = snapshotRef.current;
      const source = current.fragments.find((fragment) => fragment.id === id);
      if (!source) return;
      const spot = findFreeSpot(current, source.w, source.h, {
        x: source.x,
        y: source.y,
      });
      const copyId = uniqueFragmentId(current, id);
      applyLocal([
        {
          type: "add_fragment",
          fragment: {
            ...source,
            id: copyId,
            x: spot.x,
            y: spot.y,
            z: maxZ(current) + 1,
          },
        },
      ]);
      setSelectedId(copyId);
    },
    [applyLocal, setSelectedId],
  );

  const toWorld = useCallback(
    (client: BoardPoint): BoardPoint =>
      screenToWorld(client, viewportRef.current, paneRect),
    [paneRect],
  );

  const ordered = useMemo(
    () => [...snapshot.fragments].sort((a, b) => a.z - b.z),
    [snapshot.fragments],
  );

  return (
    <div
      ref={paneRef}
      className="relative h-full w-full overflow-hidden"
      onWheel={pointer.onOverlayWheel}
    >
      <iframe
        ref={iframeRef}
        title={BOARD_FRAME_TITLE}
        sandbox="allow-scripts"
        srcDoc={srcDoc}
        className={`absolute inset-0 h-full w-full border-0 ${
          gestureActive ? "pointer-events-none" : ""
        }`}
      />
      <OverlayLayer
        fragments={ordered}
        viewport={viewport}
        paneRect={paneRect}
        selectedId={selectedId}
        highlightedIds={highlightedIds}
        fragmentErrors={fragmentErrors}
        lastEdits={lastEdits}
        onStartMove={pointer.startMove}
        onStartResize={pointer.startResize}
        onEdit={onEditFragment}
        onDuplicate={duplicateFragment}
        onBringToFront={bringToFront}
        onDelete={removeFragment}
      />
      <DropCaptureLayer
        active={dragActive}
        toWorld={toWorld}
        onDropFragment={onDropFragment}
      />
    </div>
  );
}

/** A slug the board does not use yet, so the copy is a new fragment. */
function uniqueFragmentId(snapshot: CanvasV2Snapshot, id: string): string {
  const taken = new Set(snapshot.fragments.map((fragment) => fragment.id));
  const base = `${id.replace(/-copy(-\d+)?$/, "").slice(0, 52)}-copy`;
  if (!taken.has(base)) return base;
  for (let index = 2; index < 1000; index++) {
    const candidate = `${base}-${index}`;
    if (!taken.has(candidate)) return candidate;
  }
  return `${base}-${Date.now()}`;
}
