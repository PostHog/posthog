import type { ScoutRun } from "@posthog/api-client/posthog-client";
import { Skeleton } from "@posthog/quill";
import { ScoutRunListItem } from "./ScoutRunListItem";

export function ScoutRunsList({
  runs,
  loading,
  error,
  emptyMessage,
}: {
  runs: ScoutRun[];
  loading: boolean;
  error: boolean;
  emptyMessage: string;
}) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2].map((index) => (
          <Skeleton key={index} className="h-14 w-full" />
        ))}
      </div>
    );
  }
  if (error && runs.length === 0) {
    return (
      <p className="text-(--red-11) text-[12.5px]">
        Couldn&apos;t load runs for this agent. The agent API may be unavailable
        or this token may lack the <code>signal_scout</code> scope.
      </p>
    );
  }
  if (runs.length === 0) {
    return <p className="text-[12.5px] text-gray-11">{emptyMessage}</p>;
  }
  return (
    <div className="overflow-hidden rounded-(--radius-md) border border-border bg-(--color-panel-solid)">
      {runs.map((run, index) => (
        <ScoutRunListItem
          key={run.run_id}
          run={run}
          defaultExpanded={index === 0}
        />
      ))}
    </div>
  );
}
