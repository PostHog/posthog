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
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { ScoutTableRow } from "./ScoutTableRow";

export function ScoutTable({
  configs,
  rollups,
  creators,
  onUpdateConfig,
  emptyMessage,
}: {
  configs: ScoutConfig[];
  rollups: Map<string, ScoutRollup>;
  creators: ScoutCreatorIndex | null | undefined;
  onUpdateConfig: (configId: string, updates: ScoutConfigUpdate) => void;
  emptyMessage: string;
}) {
  const now = new Date();
  return (
    <div className="overflow-hidden rounded-(--radius-md) border border-border bg-(--color-panel-solid) [&_table]:w-full [&_table]:table-fixed">
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-[30rem]">Agent</TableHead>
            <TableHead className="w-36">Schedule</TableHead>
            <TableHead>Recent runs</TableHead>
            <TableHead className="w-44">Last run</TableHead>
            <TableHead className="w-14" />
            <TableHead className="w-10" />
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
            configs.map((config) => (
              <ScoutTableRow
                key={config.id}
                config={config}
                rollup={rollups.get(config.skill_name)}
                creator={creators?.get(config.skill_name)}
                now={now}
                onUpdate={onUpdateConfig}
              />
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
