import type { LoopSchemas } from "@posthog/api-client/loops";
import { type ReactNode, useMemo, useState } from "react";
import {
  countLoops,
  DEFAULT_LOOP_FILTERS,
  filterLoops,
  type LoopListFilters,
} from "../loopListFilters";
import type { LoopSpace } from "../loopScopes";
import { LoopsEmptyNotice, LoopsSkeleton } from "./LoopFallbacks";
import { LoopsFilterBar } from "./LoopsFilterBar";
import { LoopsTable } from "./LoopsTable";

export function LoopsListSection({
  loops,
  spaces,
  isLoading,
  error,
  showScope,
  showSpace,
  showVisibility,
  emptyState,
}: {
  loops: LoopSchemas.Loop[];
  spaces: LoopSpace[];
  isLoading: boolean;
  error: unknown;
  showScope: boolean;
  showSpace: boolean;
  showVisibility: boolean;
  emptyState: ReactNode;
}) {
  const [filters, setFilters] = useState<LoopListFilters>({
    ...DEFAULT_LOOP_FILTERS,
    scope: showScope ? "global" : "all",
  });
  const visibleLoops = useMemo(
    () => filterLoops(loops, spaces, filters),
    [loops, spaces, filters],
  );

  if (isLoading) return <LoopsSkeleton />;
  if (error) {
    return (
      <LoopsEmptyNotice
        title="Couldn't load loops."
        hint={
          error instanceof Error
            ? error.message
            : "The loops API returned an error."
        }
      />
    );
  }
  if (loops.length === 0) return emptyState;

  return (
    <div className="flex flex-col gap-3">
      <LoopsFilterBar
        filters={filters}
        counts={countLoops(loops)}
        showScope={showScope}
        showVisibility={showVisibility}
        onChange={(patch) =>
          setFilters((current) => ({ ...current, ...patch }))
        }
      />
      <LoopsTable
        loops={visibleLoops}
        spaces={spaces}
        showSpace={showSpace}
        emptyMessage={
          filters.search.trim()
            ? "No loops match your search."
            : "No loops match the current filters."
        }
      />
    </div>
  );
}
