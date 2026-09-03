import {
  type BoardPaneRect,
  type BoardPoint,
  screenToWorld,
} from "@posthog/core/canvas-v2/boardGeometry";
import type { PresencePeer } from "@posthog/core/canvas-v2/boardPresence";
import {
  type CanvasV2Fragment,
  type CanvasV2Op,
  type CanvasV2Snapshot,
  type CanvasV2Theme,
  type CanvasV2Viewport,
  maxZ,
} from "@posthog/shared";
import { BOARD_FRAME_TITLE } from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { DropCaptureLayer } from "@posthog/ui/features/canvas-v2/components/DropCaptureLayer";
import type { FragmentLastEdit } from "@posthog/ui/features/canvas-v2/components/FragmentOverlay";
import { OverlayLayer } from "@posthog/ui/features/canvas-v2/components/OverlayLayer";
import { PresenceLayer } from "@posthog/ui/features/canvas-v2/components/PresenceLayer";
import {
  useBoardHighlightedIds,
  useBoardSelectedIds,
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

/** World units a copy sits away from its source, so both stay readable. */
const DUPLICATE_OFFSET = 24;

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
  /** The other people on the board, drawn above the frame. */
  peers: readonly PresencePeer[];
  /** Where this person points, in world units, or null when off the board. */
  onCursor: (world: BoardPoint | null) => void;
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
  peers,
  onCursor,
}: BoardStageProps): ReactElement {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [paneRect, setPaneRect] = useState<BoardPaneRect>({
    left: 0,
    top: 0,
    width: 0,
    height: 0,
  });

  const selectedIds = useBoardSelectedIds();
  const highlightedIds = useBoardHighlightedIds();
  const setSelection = useBoardViewStore((state) => state.setSelection);
  const toggleSelection = useBoardViewStore((state) => state.toggleSelection);
  const clearSelection = useBoardViewStore((state) => state.clearSelection);

  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;
  const viewportRef = useRef(viewport);
  viewportRef.current = viewport;
  const selectedIdsRef = useRef(selectedIds);
  selectedIdsRef.current = selectedIds;
  const getSnapshot = useCallback(
    (): CanvasV2Snapshot => snapshotRef.current,
    [],
  );
  const getSelectedIds = useCallback(
    (): readonly string[] => selectedIdsRef.current,
    [],
  );

  const pointer = useBoardPointer({
    paneRef,
    viewport,
    setViewport,
    getSnapshot,
    applyLocal,
    getSelectedIds,
    setSelection,
    toggleSelection,
  });

  // A host drag must not let the frame swallow the pointer stream halfway
  // through. A pan is different: the frame relays that stream, so the frame
  // must stay live or the release never arrives.
  const gestureActive = pointer.gesture.kind !== "none";

  const paneRectRef = useRef(paneRect);
  paneRectRef.current = paneRect;
  // Frame points are relative to the iframe, which fills the pane.
  const reportFrameCursor = useCallback(
    (clientX: number, clientY: number): void => {
      const pane = paneRectRef.current;
      onCursor(
        screenToWorld(
          { x: clientX + pane.left, y: clientY + pane.top },
          viewportRef.current,
          pane,
        ),
      );
    },
    [onCursor],
  );

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
      onFragmentPointerDown: pointer.onFrameFragmentPointerDown,
      onPointerMove: reportFrameCursor,
      onPointerLeave: () => onCursor(null),
    },
  });
  frameRef.current = frame;

  const { ready, srcDoc, syncSnapshot } = frame;
  const setFrameViewport = frame.setViewport;
  const setFrameSelection = frame.setSelection;

  useEffect(() => {
    if (!ready) return;
    syncSnapshot(syncedSnapshot.current, snapshot);
    syncedSnapshot.current = snapshot;
  }, [ready, syncSnapshot, snapshot]);

  useEffect(() => {
    setFrameViewport(viewport);
  }, [setFrameViewport, viewport]);

  useEffect(() => {
    setFrameSelection(selectedIds);
  }, [setFrameSelection, selectedIds]);

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

  // A menu action on a selected fragment acts on the whole selection.
  const targetsOf = useCallback((id: string): string[] => {
    const selected = selectedIdsRef.current;
    return selected.includes(id) ? [...selected] : [id];
  }, []);

  const bringToFront = useCallback(
    (id: string): void => {
      const current = snapshotRef.current;
      const targets = targetsOf(id)
        .map((target) => current.fragments.find((f) => f.id === target))
        .filter((fragment): fragment is CanvasV2Fragment => Boolean(fragment))
        .sort((a, b) => a.z - b.z);
      if (targets.length === 0) return;
      applyLocal(
        targets.map((fragment) => ({
          type: "bring_to_front",
          id: fragment.id,
        })),
      );
    },
    [applyLocal, targetsOf],
  );

  const removeFragment = useCallback(
    (id: string): void => {
      applyLocal(
        targetsOf(id).map((target) => ({
          type: "remove_fragment",
          id: target,
        })),
      );
      clearSelection();
    },
    [applyLocal, clearSelection, targetsOf],
  );

  const duplicateFragment = useCallback(
    (id: string): void => {
      const current = snapshotRef.current;
      const taken = new Set(current.fragments.map((fragment) => fragment.id));
      const ops: CanvasV2Op[] = [];
      const copyIds: string[] = [];
      let top = maxZ(current);
      for (const target of targetsOf(id)) {
        const source = current.fragments.find(
          (fragment) => fragment.id === target,
        );
        if (!source) continue;
        const copyId = uniqueFragmentId(taken, target);
        taken.add(copyId);
        copyIds.push(copyId);
        top += 1;
        ops.push({
          type: "add_fragment",
          fragment: {
            ...source,
            id: copyId,
            x: source.x + DUPLICATE_OFFSET,
            y: source.y + DUPLICATE_OFFSET,
            z: top,
          },
        });
      }
      if (ops.length === 0) return;
      applyLocal(ops);
      setSelection(copyIds);
    },
    [applyLocal, setSelection, targetsOf],
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
      onPointerMove={(event) =>
        onCursor(
          screenToWorld(
            { x: event.clientX, y: event.clientY },
            viewportRef.current,
            paneRectRef.current,
          ),
        )
      }
      onPointerLeave={() => onCursor(null)}
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
        selectedIds={selectedIds}
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
      {pointer.marquee ? (
        <div
          className="pointer-events-none absolute z-20 rounded-(--radius-1) border border-(--accent-9) bg-(--accent-a3)"
          style={{
            left: pointer.marquee.left,
            top: pointer.marquee.top,
            width: pointer.marquee.width,
            height: pointer.marquee.height,
          }}
        />
      ) : null}
      <PresenceLayer
        peers={peers}
        fragments={ordered}
        viewport={viewport}
        paneRect={paneRect}
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
function uniqueFragmentId(taken: ReadonlySet<string>, id: string): string {
  const base = `${id.replace(/-copy(-\d+)?$/, "").slice(0, 52)}-copy`;
  if (!taken.has(base)) return base;
  for (let index = 2; index < 1000; index++) {
    const candidate = `${base}-${index}`;
    if (!taken.has(candidate)) return candidate;
  }
  return `${base}-${Date.now()}`;
}
