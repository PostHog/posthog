import {
  foldOps,
  type SketchpadActor,
  type SketchpadFragment,
  type SketchpadLogEntry,
  type SketchpadOp,
  type SketchpadSnapshot,
} from "@posthog/shared";

export interface HistoryGroup {
  key: string;
  actor: SketchpadActor;
  minuteIso: string;
  firstSeq: number;
  lastSeq: number;
  descriptions: string[];
  fragmentIds: string[];
}

export function describeOp(
  entry: SketchpadLogEntry,
  before: SketchpadSnapshot,
): string {
  const op = entry.op;
  switch (op.type) {
    case "add_fragment":
      return `added ${op.fragment.title ?? op.fragment.id}`;
    case "update_fragment": {
      const label = fragmentLabel(before, op.id);
      const patch = op.patch;
      if (patch.code !== undefined) return `edited the code of ${label}`;
      if (patch.title !== undefined) return `renamed ${label}`;
      if (patch.w !== undefined || patch.h !== undefined) {
        return `resized ${label}`;
      }
      if (patch.x !== undefined || patch.y !== undefined) {
        return `moved ${label}`;
      }
      if (patch.z !== undefined) return `brought ${label} to front`;
      return `changed ${label}`;
    }
    case "remove_fragment":
      return `removed ${fragmentLabel(before, op.id)}`;
    case "bring_to_front":
      return `brought ${fragmentLabel(before, op.id)} to front`;
    case "set_state":
      return op.value === null || op.value === undefined
        ? `cleared ${op.key}`
        : `changed ${op.key}`;
    case "edit_field":
      return `edited ${op.key}`;
    case "restore":
      return "restored the board";
  }
}

export function groupLogEntries(
  log: SketchpadLogEntry[],
  base: SketchpadSnapshot,
): HistoryGroup[] {
  const groups: HistoryGroup[] = [];
  let snapshot = base;
  let current: HistoryGroup | undefined;

  for (const entry of log) {
    const identity = actorIdentity(entry.actor);
    const minuteIso = toMinuteIso(entry.createdAt);
    const sameGroup =
      current !== undefined &&
      current.minuteIso === minuteIso &&
      actorIdentity(current.actor) === identity;

    if (!sameGroup) {
      current = {
        key: `${identity}|${minuteIso}|${entry.seq}`,
        actor: entry.actor,
        minuteIso,
        firstSeq: entry.seq,
        lastSeq: entry.seq,
        descriptions: [],
        fragmentIds: [],
      };
      groups.push(current);
    }

    const group = current;
    if (group) {
      const description = describeOp(entry, snapshot);
      if (!group.descriptions.includes(description)) {
        group.descriptions.push(description);
      }
      const fragmentId = touchedFragmentId(entry.op);
      if (fragmentId && !group.fragmentIds.includes(fragmentId)) {
        group.fragmentIds.push(fragmentId);
      }
      group.lastSeq = entry.seq;
    }
    if (entry.op.type !== "set_state" && entry.op.type !== "edit_field") {
      snapshot = foldOps(snapshot, [entry]);
    }
  }

  return groups.reverse();
}

export function actorIdentity(actor: SketchpadActor): string {
  if (actor.kind === "agent") return `agent:${actor.taskId ?? "unknown"}`;
  return `user:${actor.userId ?? actor.userName ?? "me"}`;
}

function fragmentLabel(snapshot: SketchpadSnapshot, id: string): string {
  const fragment: SketchpadFragment | undefined = snapshot.fragments.find(
    (candidate) => candidate.id === id,
  );
  return fragment?.title ?? id;
}

function touchedFragmentId(op: SketchpadOp): string | undefined {
  switch (op.type) {
    case "add_fragment":
      return op.fragment.id;
    case "update_fragment":
    case "remove_fragment":
    case "bring_to_front":
      return op.id;
    default:
      return undefined;
  }
}

function toMinuteIso(createdAt: string): string {
  const at = Date.parse(createdAt);
  if (Number.isNaN(at)) return createdAt;
  return `${new Date(at).toISOString().slice(0, 16)}:00.000Z`;
}
