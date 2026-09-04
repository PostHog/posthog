import {
  CANVAS_V2_FIELD_MARK,
  type CanvasV2Field,
  emptyField,
  isField,
} from "./fields";
import {
  CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT,
  CANVAS_V2_FRAGMENT_DEFAULT_WIDTH,
  type CanvasV2Fragment,
  type CanvasV2LogEntry,
  type CanvasV2Op,
  type CanvasV2Snapshot,
} from "./schemas";

export function applyOp(
  snapshot: CanvasV2Snapshot,
  op: CanvasV2Op,
): CanvasV2Snapshot {
  switch (op.type) {
    case "add_fragment": {
      const others = snapshot.fragments.filter((f) => f.id !== op.fragment.id);
      return { ...snapshot, fragments: [...others, op.fragment] };
    }
    case "update_fragment": {
      const index = snapshot.fragments.findIndex((f) => f.id === op.id);
      if (index === -1) return snapshot;
      const current = snapshot.fragments[index];
      const next: CanvasV2Fragment = { ...current, ...op.patch };
      const codeChanged =
        op.patch.code !== undefined && op.patch.code !== current.code;
      if (codeChanged && op.patch.codeVersion === undefined) {
        next.codeVersion = current.codeVersion + 1;
      }
      const fragments = snapshot.fragments.slice();
      fragments[index] = next;
      return { ...snapshot, fragments };
    }
    case "remove_fragment": {
      if (!snapshot.fragments.some((f) => f.id === op.id)) return snapshot;
      return {
        ...snapshot,
        fragments: snapshot.fragments.filter((f) => f.id !== op.id),
      };
    }
    case "bring_to_front": {
      const index = snapshot.fragments.findIndex((f) => f.id === op.id);
      if (index === -1) return snapshot;
      const top = maxZ(snapshot) + 1;
      const fragments = snapshot.fragments.slice();
      fragments[index] = { ...fragments[index], z: top };
      return { ...snapshot, fragments };
    }
    case "set_state": {
      const state = { ...snapshot.state };
      if (op.value === null || op.value === undefined) {
        delete state[op.key];
      } else {
        state[op.key] = op.value;
      }
      return { ...snapshot, state };
    }
    case "edit_field": {
      const current = snapshot.state[op.key];
      const holdsPlainValue =
        current !== undefined && current !== null && !isField(current);
      if (holdsPlainValue) return snapshot;
      const field = isField(current) ? current : emptyField(op.kind);
      if (field[CANVAS_V2_FIELD_MARK] !== op.kind) return snapshot;

      const entries = { ...field.entries };
      const removed = new Set(field.removed);
      for (const id of op.remove ?? []) {
        removed.add(id);
        delete entries[id];
      }
      for (const item of op.insert ?? []) {
        if (removed.has(item.id)) continue;
        entries[item.id] = { k: item.k, v: item.v };
      }
      const next: CanvasV2Field = {
        [CANVAS_V2_FIELD_MARK]: op.kind,
        entries,
        removed: [...removed],
      };
      return { ...snapshot, state: { ...snapshot.state, [op.key]: next } };
    }
    case "restore":
      return {
        schemaVersion: 1,
        fragments: op.snapshot.fragments.map((f) => ({ ...f })),
        state: { ...op.snapshot.state },
      };
  }
}

export function foldOps(
  snapshot: CanvasV2Snapshot,
  entries: readonly Pick<CanvasV2LogEntry, "op">[],
): CanvasV2Snapshot {
  let current = snapshot;
  const start = Math.max(
    0,
    entries.findLastIndex(({ op }) => op.type === "restore"),
  );
  for (let index = start; index < entries.length; index++) {
    current = applyOp(current, entries[index].op);
  }
  return current;
}

export function maxZ(snapshot: CanvasV2Snapshot): number {
  let top = 0;
  for (const f of snapshot.fragments) if (f.z > top) top = f.z;
  return top;
}

/** A frame goes under everything, so the fragments inside it stay clickable. */
export function minZ(snapshot: CanvasV2Snapshot): number {
  let bottom = 0;
  for (const f of snapshot.fragments) if (f.z < bottom) bottom = f.z;
  return bottom;
}

/** True when two fragments draw the same thing in the same place. */
export function fragmentsEqual(
  a: CanvasV2Fragment,
  b: CanvasV2Fragment,
): boolean {
  return (
    a.title === b.title &&
    a.x === b.x &&
    a.y === b.y &&
    a.w === b.w &&
    a.h === b.h &&
    a.z === b.z &&
    a.code === b.code &&
    a.codeVersion === b.codeVersion &&
    a.surface === b.surface &&
    a.hidden === b.hidden
  );
}

const GRID = 40;
const GAP = 24;

export function findFreeSpot(
  snapshot: CanvasV2Snapshot,
  w: number = CANVAS_V2_FRAGMENT_DEFAULT_WIDTH,
  h: number = CANVAS_V2_FRAGMENT_DEFAULT_HEIGHT,
  origin: { x: number; y: number } = { x: 0, y: 0 },
): { x: number; y: number } {
  const startX = Math.round(origin.x / GRID) * GRID;
  const startY = Math.round(origin.y / GRID) * GRID;
  for (let row = 0; row < 200; row++) {
    for (let col = 0; col < 200; col++) {
      const x = startX + col * GRID;
      const y = startY + row * GRID;
      if (!overlapsAny(snapshot, x, y, w, h)) return { x, y };
    }
  }
  return { x: startX, y: startY + maxBottom(snapshot) + GAP };
}

function overlapsAny(
  snapshot: CanvasV2Snapshot,
  x: number,
  y: number,
  w: number,
  h: number,
): boolean {
  return snapshot.fragments.some(
    (f) =>
      x < f.x + f.w + GAP &&
      x + w + GAP > f.x &&
      y < f.y + f.h + GAP &&
      y + h + GAP > f.y,
  );
}

function maxBottom(snapshot: CanvasV2Snapshot): number {
  let bottom = 0;
  for (const f of snapshot.fragments) bottom = Math.max(bottom, f.y + f.h);
  return bottom;
}

export function opIdForToolCall(toolCallId: string, index = 0): string {
  const suffix = index === 0 ? "" : `-${index}`;
  return `tool-${sanitizeId(toolCallId)}${suffix}`;
}

function sanitizeId(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 48);
}

export function estimateJsonBytes(value: unknown): number {
  try {
    return new TextEncoder().encode(JSON.stringify(value) ?? "").length;
  } catch {
    return Number.POSITIVE_INFINITY;
  }
}
