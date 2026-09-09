import type { Command } from "@posthog/ui/features/command/commandRow";
import {
  type ResultRow,
  rankResultRows,
} from "@posthog/ui/features/command/rankResultRows";
import { describe, expect, it } from "vitest";

const row = (
  label: string,
  kind: ResultRow["kind"],
  recency?: number,
): ResultRow => ({
  kind,
  recency,
  command: {
    id: label,
    label,
    icon: null,
    action: "open-task",
    onRun: () => {},
  } satisfies Command,
});

const labels = (rows: ResultRow[], query: string): string[] =>
  rankResultRows(rows, query).map((command) => command.label);

describe("rankResultRows", () => {
  it("puts an exact title above a stronger-kind partial match", () => {
    const rows = [
      row("export the retention chart", "task"),
      row("export", "artifact"),
    ];

    expect(labels(rows, "export")).toEqual([
      "export",
      "export the retention chart",
    ]);
  });

  it("prefers a task over a file when both match a word in the title", () => {
    const rows = [
      row("export-timeout.md", "artifact"),
      row("Export reliability review", "canvas"),
      row("triage the failing export job", "task"),
    ];

    expect(labels(rows, "export")).toEqual([
      "triage the failing export job",
      "Export reliability review",
      "export-timeout.md",
    ]);
  });

  it("puts a title match above a row matched by its keywords alone", () => {
    const rows = [row("PR #4821", "pull_request"), row("export job", "task")];

    expect(labels(rows, "export")).toEqual(["export job", "PR #4821"]);
  });

  it("breaks a tie on what changed last", () => {
    const rows = [
      row("export job A", "task", 1_000),
      row("export job B", "task", 5_000),
    ];

    expect(labels(rows, "export")).toEqual(["export job B", "export job A"]);
  });

  it("keeps the incoming order when there is no query", () => {
    const rows = [row("b", "task"), row("a", "task")];

    expect(labels(rows, "  ")).toEqual(["b", "a"]);
  });
});
