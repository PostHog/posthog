import { ArrowsInIcon } from "@phosphor-icons/react";
import {
  type BoardPaneRect,
  type BoardPoint,
  screenToWorld,
} from "@posthog/core/canvas-v2/boardGeometry";
import type { PresencePeer } from "@posthog/core/canvas-v2/boardPresence";
import { Button, Kbd } from "@posthog/quill";
import {
  type CanvasV2Fragment,
  type CanvasV2FrameCaret,
  type CanvasV2Op,
  type CanvasV2PresenceCaret,
  type CanvasV2Snapshot,
  type CanvasV2Theme,
  type CanvasV2Viewport,
  maxZ,
} from "@posthog/shared";
import { EXIT_FULL_SCREEN_ACTION } from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import {
  BoardFrame,
  type BoardFrameHealth,
} from "@posthog/ui/features/canvas-v2/components/BoardFrame";
import { BoardHealthNotice } from "@posthog/ui/features/canvas-v2/components/BoardHealthNotice";
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
import type { BoardFrameElement } from "@posthog/ui/features/canvas-v2/runtime/boardFrameElement";
import {
  type BoardFrameHandle,
  useBoardFrame,
} from "@posthog/ui/features/canvas-v2/runtime/useBoardFrame";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
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
  applyLocal: (ops: CanvasV2Op[], opIds?: string[]) => void;
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
  /** Where this person edits a shared field, or null when they left it. */
  onCaret: (caret: CanvasV2PresenceCaret | null) => void;
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
  onCaret,
}: BoardStageProps): ReactElement {
  const [frameElement, setFrameElement] = useState<BoardFrameElement | null>(
    null,
  );
  const { vendoredCanvasModules } = useHostCapabilities();
  const [frameHealth, setFrameHealth] = useState<BoardFrameHealth>("running");
  const [stopped, setStopped] = useState(false);
  const [paneRect, setPaneRect] = useState<BoardPaneRect>({
    left: 0,
    top: 0,
    width: 0,
    height: 0,
  });

  const selectedIds = useBoardSelectedIds();
  const highlightedIds = useBoardHighlightedIds();
  const focusedId = useBoardViewStore((state) => state.focusedId);
  const setFocusedId = useBoardViewStore((state) => state.setFocusedId);
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

  const focusedRef = useRef(focusedId);
  focusedRef.current = focusedId;
  const whenOnBoard = useCallback(
    <T extends unknown[]>(handler: (...args: T) => void) =>
      (...args: T): void => {
        if (focusedRef.current === null) handler(...args);
      },
    [],
  );

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
    frameElement,
    theme,
    queryClient,
    getSnapshot,
    applyLocal,
    reportCaret: onCaret,
    events: {
      onExitFocus: () => setFocusedId(null),
      onReady: () => {
        syncedSnapshot.current = snapshotRef.current;
        frameRef.current?.sendInit(viewportRef.current);
        frameRef.current?.setFocus(focusedRef.current);
      },
      onFragmentRendered: (id) => onFragmentError(id, null),
      onFragmentError: (id, message) => onFragmentError(id, message),
      onStateChanged: (key, value) =>
        applyLocal([{ type: "set_state", key, value }]),
      onWheel: whenOnBoard(pointer.onFrameWheel),
      onBackgroundPointer: whenOnBoard(pointer.onFrameBackgroundPointer),
      onFragmentPointerDown: whenOnBoard(pointer.onFrameFragmentPointerDown),
      onPointerMove: reportFrameCursor,
      onPointerLeave: () => onCursor(null),
    },
  });
  frameRef.current = frame;

  const { documentReady, ready, srcDoc, syncSnapshot } = frame;
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
    if (focusedId === null) return;
    if (!snapshot.fragments.some((fragment) => fragment.id === focusedId)) {
      setFocusedId(null);
    }
  }, [focusedId, setFocusedId, snapshot.fragments]);

  const setFrameFocus = frame.setFocus;
  useEffect(() => {
    setFrameFocus(focusedId);
    if (focusedId !== null) frameElement?.focus();
  }, [setFrameFocus, focusedId, frameElement]);

  const setFrameBusy = frame.setBusy;
  useEffect(() => {
    setFrameBusy(gestureActive);
  }, [setFrameBusy, gestureActive]);

  useEffect(() => {
    if (focusedId === null) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") setFocusedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [focusedId, setFocusedId]);

  const setFrameCarets = frame.setCarets;
  const frameCarets = useMemo<CanvasV2FrameCaret[]>(
    () =>
      peers.flatMap((peer) =>
        peer.carets.map((caret) => ({
          clientId: peer.clientId,
          name: peer.name,
          color: peer.color.bg,
          textColor: peer.color.text,
          key: caret.key,
          anchor: caret.anchor,
          focus: caret.focus,
        })),
      ),
    [peers],
  );

  useEffect(() => {
    setFrameCarets(frameCarets);
  }, [setFrameCarets, frameCarets]);

  useEffect(() => {
    const pane = paneRef.current;
    if (!pane) return;
    const measure = (): void => {
      const rect = pane.getBoundingClientRect();
      const previous = paneRectRef.current;
      const shift = rect.left - previous.left;
      if (previous.width > 0 && shift !== 0 && focusedRef.current === null) {
        const current = viewportRef.current;
        setViewport({ ...current, x: current.x - shift });
      }
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
  }, [paneRef, setViewport]);

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
      onWheel={whenOnBoard(pointer.onOverlayWheel)}
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
      <BoardFrame
        onElement={setFrameElement}
        stopped={stopped}
        onHealth={setFrameHealth}
        srcDoc={srcDoc}
        vendored={vendoredCanvasModules}
        documentReady={documentReady}
        inert={gestureActive}
      />
      <BoardHealthNotice
        health={frameHealth}
        stopped={stopped}
        onStop={() => {
          setStopped(true);
          setFrameHealth("running");
        }}
        onStart={() => setStopped(false)}
      />
      {focusedId === null ? (
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
          onFocus={setFocusedId}
        />
      ) : (
        <div className="absolute bottom-4 left-4 z-[60] opacity-70 transition-opacity hover:opacity-100">
          <Button
            variant="default"
            size="sm"
            className="gap-2 rounded-full border border-(--gray-a6) bg-(--gray-1)/90 shadow-lg backdrop-blur-md"
            onClick={() => setFocusedId(null)}
          >
            <ArrowsInIcon />
            {EXIT_FULL_SCREEN_ACTION}
            <Kbd>Esc</Kbd>
          </Button>
        </div>
      )}
      {pointer.marquee && focusedId === null ? (
        <div
          className="pointer-events-none absolute z-20 rounded-(--radius-1) border border-(--accent-a9) bg-(--accent-a2)"
          style={{
            left: pointer.marquee.left,
            top: pointer.marquee.top,
            width: pointer.marquee.width,
            height: pointer.marquee.height,
          }}
        />
      ) : null}
      {focusedId === null ? (
        <PresenceLayer
          peers={peers}
          fragments={ordered}
          viewport={viewport}
          paneRect={paneRect}
        />
      ) : null}
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
