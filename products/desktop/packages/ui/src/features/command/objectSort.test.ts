import type { Command } from "@posthog/ui/features/command/commandRow";
import {
  type ObjectSort,
  objectRowSections,
  type SortableObjectRow,
  sortObjectRows,
} from "@posthog/ui/features/command/objectSort";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const NOW = new Date(2026, 5, 15, 12, 0, 0).getTime();
const DAY = 86_400_000;

const row = (
  label: string,
  viewedAt?: number,
  createdAt?: number,
): SortableObjectRow => ({
  viewedAt,
  createdAt,
  command: {
    id: label,
    label,
    icon: null,
    action: "open-task",
    onRun: () => {},
  } satisfies Command,
});

const rows = [
  row("beta", undefined, NOW - 40 * DAY),
  row("Alpha 10", NOW - DAY, NOW - 2 * DAY),
  row("alpha 9", NOW - 3 * DAY, Number.NaN),
  row("gamma", NOW + DAY, NOW),
];

const sectionsFor = (sort: ObjectSort) =>
  objectRowSections(sortObjectRows(rows, sort), "Matching tasks").map(
    (section) => [section.label, section.items.map((item) => item.label)],
  );

describe("sortObjectRows", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });
  afterEach(() => vi.useRealTimers());

  it.each<[ObjectSort, [string, string[]][]]>([
    [
      "recent",
      [
        // A view stamped ahead of the local clock still counts as today.
        ["Today", ["gamma"]],
        ["Yesterday", ["Alpha 10"]],
        ["This week", ["alpha 9"]],
        ["Not opened yet", ["beta"]],
      ],
    ],
    [
      "created",
      [
        ["Today", ["gamma"]],
        ["This week", ["Alpha 10"]],
        ["Earlier", ["beta"]],
        ["No date", ["alpha 9"]],
      ],
    ],
    ["name", [["Matching tasks", ["alpha 9", "Alpha 10", "beta", "gamma"]]]],
  ])("groups a %s sort", (sort, expected) => {
    expect(sectionsFor(sort)).toEqual(expected);
  });
});
