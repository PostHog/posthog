import type {
  CanvasAnalyticsConfig,
  CanvasNavIntent,
} from "@posthog/core/canvas/freeformSchemas";
import { create } from "zustand";

// A warm-iframe pool for canvases. The expensive part of opening a canvas is the
// iframe cold-boot (Babel + Tailwind + React + Quill + esm.sh), which is IDENTICAL
// across canvases. The sandbox's `init` message swaps the rendered canvas in place
// without reloading, so a booted iframe can be re-pointed at a different canvas's
// code. We therefore keep a small pool of physical frames (indexed slots) alive in
// the persistent WebsiteLayout and assign canvases to them: the first few distinct
// canvases each boot a frame; after the pool is full, a new canvas reuses the
// least-recently-active frame via an init code-swap — no reload.
//
// The pool is keyed by SLOT INDEX (stable React key) so reassigning a slot reuses
// its iframe. An iframe must never be re-parented (that forces a reload), so the
// host renders the frames and overlays each onto the active route's placeholder
// rect rather than mounting the iframe inside the route tree.

export interface CanvasFrameRect {
  top: number;
  left: number;
  width: number;
  height: number;
}

// Per-canvas inputs for its FreeformCanvas. Callbacks are stable (module fn /
// useCallback / useMemo) so re-registering on each commit is cheap.
export interface CanvasFrameInputs {
  code: string;
  analytics?: CanvasAnalyticsConfig;
  onDataRequest: (method: string, payload: unknown) => Promise<unknown>;
  onError?: (message: string, stack?: string) => void;
  onRendered?: () => void;
  onNavigate?: (intent: CanvasNavIntent) => void;
}

interface CanvasFrameSlot {
  dashboardId: string;
  inputs: CanvasFrameInputs;
  rect: CanvasFrameRect | null;
  lastActiveAt: number;
}

interface CanvasFrameStore {
  // Physical frames, indexed by slot. `null` = an unused slot (pool not yet full).
  slots: (CanvasFrameSlot | null)[];
  activeDashboardId: string | null;
  maxWarmFrames: number;
  // Per-slot remount generation. Folded into the frame's React key by the host,
  // so bumping it tears down and recreates that slot's iframe element (a true
  // remount, unlike a code-swap). Keyed by SLOT INDEX, not canvas, and only ever
  // bumped by an explicit user refresh — so reassigning a slot to another canvas
  // (navigation) leaves it untouched and still reuses the warm iframe.
  frameKeys: Record<number, number>;

  register: (dashboardId: string, inputs: CanvasFrameInputs) => void;
  setRect: (dashboardId: string, rect: CanvasFrameRect) => void;
  activate: (dashboardId: string) => void;
  deactivate: (dashboardId: string) => void;
  remount: (dashboardId: string) => void;
  setMaxWarmFrames: (n: number) => void;
}

// Monotonic so LRU ordering never depends on wall-clock resolution.
let activationSeq = 0;

const DEFAULT_MAX_WARM_FRAMES = 2;

function findSlot(
  slots: (CanvasFrameSlot | null)[],
  dashboardId: string,
): number {
  return slots.findIndex((s) => s?.dashboardId === dashboardId);
}

// Assigns `dashboardId` to a slot, reusing its existing slot, an empty slot, or —
// when the pool is full — the least-recently-active slot other than the active one
// (an init code-swap on that frame). Returns the (possibly new) slots array.
function assignSlot(
  slots: (CanvasFrameSlot | null)[],
  maxWarmFrames: number,
  activeDashboardId: string | null,
  dashboardId: string,
  inputs: CanvasFrameInputs,
): (CanvasFrameSlot | null)[] {
  const next = slots.slice(0, maxWarmFrames);
  while (next.length < maxWarmFrames) next.push(null);

  const existing = next.findIndex((s) => s?.dashboardId === dashboardId);
  if (existing >= 0) {
    const slot = next[existing] as CanvasFrameSlot;
    next[existing] = { ...slot, inputs };
    return next;
  }

  let idx = next.findIndex((s) => s == null);
  if (idx < 0) {
    let lru = -1;
    let lruAt = Number.POSITIVE_INFINITY;
    for (let i = 0; i < next.length; i++) {
      const slot = next[i];
      if (!slot || slot.dashboardId === activeDashboardId) continue;
      if (slot.lastActiveAt < lruAt) {
        lruAt = slot.lastActiveAt;
        lru = i;
      }
    }
    // Fall back to slot 0 if every slot is the active one (only at pool size 1).
    idx = lru >= 0 ? lru : 0;
  }

  next[idx] = {
    dashboardId,
    inputs,
    rect: null,
    lastActiveAt: ++activationSeq,
  };
  return next;
}

export const useCanvasFrameStore = create<CanvasFrameStore>()((set) => ({
  slots: [],
  activeDashboardId: null,
  maxWarmFrames: DEFAULT_MAX_WARM_FRAMES,
  frameKeys: {},

  register: (dashboardId, inputs) =>
    set((s) => ({
      slots: assignSlot(
        s.slots,
        s.maxWarmFrames,
        s.activeDashboardId,
        dashboardId,
        inputs,
      ),
    })),

  setRect: (dashboardId, rect) =>
    set((s) => {
      const idx = findSlot(s.slots, dashboardId);
      if (idx < 0) return s;
      const slot = s.slots[idx] as CanvasFrameSlot;
      // Skip no-op rect writes so scroll/resize spam doesn't re-render the host.
      const prev = slot.rect;
      if (
        prev &&
        prev.top === rect.top &&
        prev.left === rect.left &&
        prev.width === rect.width &&
        prev.height === rect.height
      ) {
        return s;
      }
      const slots = s.slots.slice();
      slots[idx] = { ...slot, rect };
      return { slots };
    }),

  activate: (dashboardId) =>
    set((s) => {
      const idx = findSlot(s.slots, dashboardId);
      if (idx < 0) return { activeDashboardId: dashboardId };
      const slots = s.slots.slice();
      slots[idx] = {
        ...(slots[idx] as CanvasFrameSlot),
        lastActiveAt: ++activationSeq,
      };
      return { slots, activeDashboardId: dashboardId };
    }),

  deactivate: (dashboardId) =>
    set((s) =>
      s.activeDashboardId === dashboardId ? { activeDashboardId: null } : s,
    ),

  // Force a full remount of the canvas's mounted iframe (recreate the element +
  // its sandboxed document), for a manual "Refresh" that must recover from a
  // wedged frame, not just reload the document. No-op if the canvas has no slot.
  remount: (dashboardId) =>
    set((s) => {
      const idx = findSlot(s.slots, dashboardId);
      if (idx < 0) return s;
      return {
        frameKeys: { ...s.frameKeys, [idx]: (s.frameKeys[idx] ?? 0) + 1 },
      };
    }),

  setMaxWarmFrames: (n) =>
    set((s) => ({
      maxWarmFrames: Math.max(1, n),
      slots: s.slots.slice(0, Math.max(1, n)),
    })),
}));
