import type { TaskSearchResult } from "@posthog/shared/domain-types";
import type { Command } from "@posthog/ui/features/command/commandRow";

export type ResultRow = {
  command: Command;
  kind: TaskSearchResult["kind"];
  recency?: number;
};

const KIND_WEIGHT: Record<TaskSearchResult["kind"], number> = {
  task: 0,
  channel: 0,
  canvas: 1,
  pull_request: 2,
  artifact: 2,
};

const WORD_SEPARATORS = /[\s\-_/.:#]+/;

const EXACT_TITLE = 0;
const WORD_START = 1;
const IN_TITLE = 2;
const MATCHED_ELSEWHERE = 3;

function matchTier(label: string, query: string): number {
  const title = label.trim().toLowerCase();
  if (title === query) return EXACT_TITLE;
  if (title.startsWith(query)) return WORD_START;
  if (title.split(WORD_SEPARATORS).some((word) => word.startsWith(query))) {
    return WORD_START;
  }
  return title.includes(query) ? IN_TITLE : MATCHED_ELSEWHERE;
}

export function rankResultRows(rows: ResultRow[], query: string): Command[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return rows.map((row) => row.command);
  return rows
    .map((row, order) => ({
      row,
      order,
      tier: matchTier(row.command.label, normalizedQuery),
    }))
    .sort(
      (left, right) =>
        left.tier - right.tier ||
        KIND_WEIGHT[left.row.kind] - KIND_WEIGHT[right.row.kind] ||
        (right.row.recency ?? 0) - (left.row.recency ?? 0) ||
        left.order - right.order,
    )
    .map(({ row }) => row.command);
}
