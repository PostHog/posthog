import type { LoopSchemas } from "@posthog/api-client/loops";
import { type LoopSpace, resolveLoopScope } from "./loopScopes";

export type LoopScopeFilter = "all" | "global";
export type LoopVisibilityFilter = "all" | LoopSchemas.LoopVisibilityEnum;

export interface LoopListFilters {
  scope: LoopScopeFilter;
  visibility: LoopVisibilityFilter;
  search: string;
  hidePaused: boolean;
}

export const DEFAULT_LOOP_FILTERS: LoopListFilters = {
  scope: "global",
  visibility: "all",
  search: "",
  hidePaused: false,
};

export function filterLoops(
  loops: LoopSchemas.Loop[],
  spaces: LoopSpace[],
  filters: LoopListFilters,
): LoopSchemas.Loop[] {
  const query = filters.search.trim().toLowerCase();
  return loops.filter((loop) => {
    const scope = resolveLoopScope(loop, spaces);
    if (filters.scope === "global" && scope.kind !== "global") return false;
    if (filters.visibility !== "all" && loop.visibility !== filters.visibility)
      return false;
    if (filters.hidePaused && !loop.enabled) return false;
    if (!query) return true;
    return [loop.name, loop.description, scope.label].some((value) =>
      value.toLowerCase().includes(query),
    );
  });
}

export interface LoopCounts {
  total: number;
  active: number;
  team: number;
  personal: number;
  global: number;
  spaces: number;
  autoPaused: number;
}

export function countLoops(loops: LoopSchemas.Loop[]): LoopCounts {
  const spaceIds = new Set<string>();
  const counts: LoopCounts = {
    total: loops.length,
    active: 0,
    team: 0,
    personal: 0,
    global: 0,
    spaces: 0,
    autoPaused: 0,
  };
  for (const loop of loops) {
    if (loop.enabled) counts.active += 1;
    else if (loop.disabled_reason) counts.autoPaused += 1;
    if (loop.visibility === "team") counts.team += 1;
    else counts.personal += 1;
    if (loop.context_target) spaceIds.add(loop.context_target.channel_id);
    else counts.global += 1;
  }
  counts.spaces = spaceIds.size;
  return counts;
}
