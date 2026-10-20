import { blockDefinition } from "@posthog/core/canvas/blockLibrary/blockDefinitions";
import type { SourceDropTarget } from "@posthog/core/canvas/blockLibrary/sourceEdits";
import type { CanvasEditSelection } from "@posthog/ui/features/canvas/blocks/canvasSourceStore";
import {
  canvasEditorFrame,
  postToCanvasEditor,
} from "@posthog/ui/features/canvas/blocks/editorFrame";
import { libraryLabel } from "@posthog/ui/features/canvas/blocks/libraryCatalog";
import { create } from "zustand";

export type SourceDragSource =
  | { kind: "new"; blockType: string }
  | { kind: "move"; selection: CanvasEditSelection };

export interface SourceDropHit {
  rev: number;
  target: SourceDropTarget;
}

interface GhostState {
  label: string;
  blockType: string | null;
  x: number;
  y: number;
  tilt: number;
  hint: string | null;
  phase: GhostPhase;
}

export type GhostPhase = "drag" | "drop" | "return";

interface SourceDragStore {
  ghost: GhostState | null;
  setGhost: (ghost: GhostState | null) => void;
}

export const useSourceDragStore = create<SourceDragStore>((set) => ({
  ghost: null,
  setGhost: (ghost) => set({ ghost }),
}));

const ACTIVATION_DISTANCE = 4;
const MAX_TILT = 3;
const TILT_GAIN = 0.3;
const TILT_EASE = 0.18;
const DROP_EXIT_MS = 140;
const RETURN_EXIT_MS = 280;

let exitTimer: ReturnType<typeof setTimeout> | null = null;

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function leaveGhost(ghost: GhostState, duration: number): void {
  const { setGhost } = useSourceDragStore.getState();
  if (exitTimer) clearTimeout(exitTimer);
  setGhost(ghost);
  exitTimer = setTimeout(() => {
    exitTimer = null;
    if (useSourceDragStore.getState().ghost?.phase !== "drag") setGhost(null);
  }, duration);
}

export interface SourceDragController {
  move: (clientX: number, clientY: number) => void;
  hit: (hit: SourceDropHit | null) => void;
  end: (commit: boolean) => void;
}

let active: SourceDragController | null = null;

export function activeSourceDrag(): SourceDragController | null {
  return active;
}

function hintFor(hit: SourceDropHit | null): string {
  if (!hit) return "Drop on the canvas";
  if (hit.target.place === "left" || hit.target.place === "right")
    return "Place side by side";
  if (hit.target.place === "inside") return "Add at the end";
  return "Place here";
}

function isDataBlock(blockType: string | null): boolean {
  return !!blockType && blockDefinition(blockType)?.group === "Data";
}

export function beginSourceDrag(options: {
  source: SourceDragSource;
  startX: number;
  startY: number;
  onDrop: (source: SourceDragSource, hit: SourceDropHit) => void;
  onClick?: () => void;
}): void {
  const { setGhost } = useSourceDragStore.getState();
  const { source } = options;
  const blockType =
    source.kind === "new" ? source.blockType : source.selection.blockType;
  const label = libraryLabel(
    blockType,
    source.kind === "move" ? source.selection.tag : undefined,
  );
  let started = source.kind === "move";
  let lastX = options.startX;
  let tilt = 0;
  let latestHit: SourceDropHit | null = null;
  const coarse = isDataBlock(blockType);
  const reduceMotion = prefersReducedMotion();
  let lastGhost: GhostState | null = null;
  const exclude =
    source.kind === "move" && source.selection.source
      ? `${source.selection.source.file}|${source.selection.source.start}|${source.selection.source.end}`
      : null;

  const render = (x: number, y: number) => {
    const velocity = x - lastX;
    lastX = x;
    const wanted = Math.max(
      -MAX_TILT,
      Math.min(MAX_TILT, velocity * TILT_GAIN),
    );
    tilt += (wanted - tilt) * TILT_EASE;
    if (exitTimer) {
      clearTimeout(exitTimer);
      exitTimer = null;
    }
    const ghost: GhostState = {
      label,
      blockType,
      x,
      y,
      tilt: reduceMotion ? 0 : tilt,
      hint: hintFor(latestHit),
      phase: "drag",
    };
    lastGhost = ghost;
    setGhost(ghost);
  };

  const forward = (x: number, y: number) => {
    const frame = canvasEditorFrame();
    const rect = frame?.getBoundingClientRect();
    const inside =
      !!rect &&
      x >= rect.left &&
      x <= rect.right &&
      y >= rect.top &&
      y <= rect.bottom;
    if (!rect || !inside) {
      latestHit = null;
      postToCanvasEditor({ type: "canvas-edit-drag-end" });
      return;
    }
    postToCanvasEditor({
      type: "canvas-edit-drag-move",
      x: x - rect.left,
      y: y - rect.top,
      exclude,
      coarse,
    });
  };

  const controller: SourceDragController = {
    move(x, y) {
      if (!started) {
        if (
          Math.hypot(x - options.startX, y - options.startY) <
          ACTIVATION_DISTANCE
        )
          return;
        started = true;
      }
      render(x, y);
      forward(x, y);
    },
    hit(hit) {
      latestHit = hit;
    },
    end(commit) {
      window.removeEventListener("pointermove", onMove, true);
      window.removeEventListener("pointerup", onUp, true);
      window.removeEventListener("keydown", onKey, true);
      postToCanvasEditor({ type: "canvas-edit-drag-end", final: true });
      active = null;
      if (!started || !lastGhost) {
        setGhost(null);
        if (commit && !started) options.onClick?.();
        return;
      }
      const dropped = commit && !!latestHit;
      if (dropped && latestHit) {
        leaveGhost({ ...lastGhost, phase: "drop" }, DROP_EXIT_MS);
        options.onDrop(source, latestHit);
        return;
      }
      leaveGhost(
        {
          ...lastGhost,
          x: options.startX,
          y: options.startY,
          tilt: 0,
          phase: "return",
        },
        reduceMotion ? DROP_EXIT_MS : RETURN_EXIT_MS,
      );
    },
  };

  const onMove = (event: PointerEvent) =>
    controller.move(event.clientX, event.clientY);
  const onUp = () => controller.end(true);
  const onKey = (event: KeyboardEvent) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    controller.end(false);
  };

  window.addEventListener("pointermove", onMove, true);
  window.addEventListener("pointerup", onUp, true);
  window.addEventListener("keydown", onKey, true);
  active = controller;
  if (started) render(options.startX, options.startY);
}
