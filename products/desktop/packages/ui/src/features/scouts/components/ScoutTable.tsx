import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import type {
  ScoutCreatorIndex,
  ScoutRollup,
} from "@posthog/core/scouts/scoutPresentation";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@posthog/quill";
import { useMinuteNow } from "@posthog/ui/hooks/useMinuteNow";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useRef } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { ScoutTableRow } from "./ScoutTableRow";

/** Close enough for the scrollbar; each row measures itself once it renders. */
const ESTIMATED_ROW_HEIGHT = 52;

/**
 * The fleet, one agent per row. A project can hold hundreds of agents, so only
 * the rows in view are rendered: drawing them all costs about a second of
 * frozen screen every time the page opens.
 */
export function ScoutTable({
  configs,
  rollups,
  runsPending,
  creators,
  onUpdateConfig,
  emptyMessage,
}: {
  configs: ScoutConfig[];
  rollups: Map<string, ScoutRollup>;
  /** Run history has not answered yet, so the runs column waits rather than reads empty. */
  runsPending: boolean;
  creators: ScoutCreatorIndex | null | undefined;
  onUpdateConfig: (configId: string, updates: ScoutConfigUpdate) => void;
  emptyMessage: string;
}) {
  // One `now` for every row, changing on the minute: a fresh Date each render
  // would re-do the work of every visible row on every scroll frame.
  const now = useMinuteNow();
  const viewportRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: configs.length,
    getScrollElement: () => viewportRef.current,
    estimateSize: () => ESTIMATED_ROW_HEIGHT,
    overscan: 8,
    getItemKey: (index) => configs[index]?.id ?? index,
  });
  const virtualRows = virtualizer.getVirtualItems();
  const topSpacer = virtualRows[0]?.start ?? 0;
  const bottomSpacer =
    virtualizer.getTotalSize() -
    (virtualRows[virtualRows.length - 1]?.end ?? 0);

  return (
    <Table
      viewportRef={viewportRef}
      stickyHeader
      fullWidth
      tableClassName="table-fixed"
      className="@container h-full rounded-(--radius-md) border border-border bg-(--color-panel-solid)"
    >
      <TableHeader>
        <TableRow className="hover:bg-transparent">
          {/* Percentages per breakpoint. A `table-fixed` column with no width
              of its own takes every spare pixel, and a hidden column keeps its
              share, so each set has to add up to 100 on its own. */}
          <TableHead className="@2xl:w-[44%] @4xl:w-[32%] w-[66%]">
            Agent
          </TableHead>
          <TableHead className="@2xl:w-[16%] @4xl:w-[13%] w-[22%]">
            Schedule
          </TableHead>
          <TableHead className="@4xl:table-cell hidden @4xl:w-[27%]">
            Recent runs
          </TableHead>
          <TableHead className="@2xl:table-cell hidden @2xl:w-[28%] @4xl:w-[18%]">
            Last run
          </TableHead>
          <TableHead className="@4xl:w-[6%] w-[7%]" />
          <TableHead className="@4xl:w-[4%] w-[5%]" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {configs.length === 0 ? (
          <TableRow className="hover:bg-transparent">
            <TableCell
              colSpan={6}
              className="py-10 text-center text-[12.5px] text-gray-10"
            >
              {emptyMessage}
            </TableCell>
          </TableRow>
        ) : (
          <>
            {topSpacer > 0 ? (
              <TableRow aria-hidden className="hover:bg-transparent">
                <TableCell colSpan={6} style={{ height: topSpacer }} />
              </TableRow>
            ) : null}
            {virtualRows.map((virtualRow) => {
              const config = configs[virtualRow.index];
              if (!config) return null;
              return (
                <ScoutTableRow
                  key={config.id}
                  measureRef={virtualizer.measureElement}
                  index={virtualRow.index}
                  config={config}
                  rollup={rollups.get(config.skill_name)}
                  runsPending={runsPending}
                  creator={creators?.get(config.skill_name)}
                  now={now}
                  onUpdate={onUpdateConfig}
                />
              );
            })}
            {bottomSpacer > 0 ? (
              <TableRow aria-hidden className="hover:bg-transparent">
                <TableCell colSpan={6} style={{ height: bottomSpacer }} />
              </TableRow>
            ) : null}
          </>
        )}
      </TableBody>
    </Table>
  );
}
