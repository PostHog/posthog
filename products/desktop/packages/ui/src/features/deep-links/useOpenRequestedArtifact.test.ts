import type { TaskRun } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { findArtifactInRuns } from "./useOpenRequestedArtifact";

function run(id: string, artifacts: Record<string, unknown>[]): TaskRun {
  return { id, artifacts } as unknown as TaskRun;
}

const runs = [
  run("run-2", [
    { id: "art-2", name: "report.md", type: "output", storage_path: "s/2" },
    { id: "ref-1", name: "Insight", type: "reference" },
  ]),
  run("run-1", [
    { id: "art-1", name: "report.md", type: "output", storage_path: "s/1" },
  ]),
];

describe("findArtifactInRuns", () => {
  it.each([
    [
      "an artifact on the newest run",
      "art-2",
      { runId: "run-2", name: "report.md" },
    ],
    [
      "an older version on an earlier run",
      "art-1",
      { runId: "run-1", name: "report.md" },
    ],
    ["a reference entry, which has no file to open", "ref-1", null],
    ["an unknown id", "missing", null],
  ])("resolves %s", (_label, artifactId, expected) => {
    expect(findArtifactInRuns(runs, artifactId)).toEqual(expected);
  });
});
