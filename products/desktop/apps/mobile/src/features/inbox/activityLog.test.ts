import {
  attributionLabel,
  taskRunLabel,
} from "@posthog/core/inbox/activityLog";
import type { AnySignalReportArtefact } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  parseDiffLines,
  selectActivityArtefacts,
  shortSha,
} from "./activityLog";

function commit(id: string, createdAt: string): AnySignalReportArtefact {
  return {
    id,
    type: "commit",
    created_at: createdAt,
    content: {
      repository: "posthog/posthog",
      branch: "main",
      commit_sha: "abcdef1234567890",
      message: "fix",
    },
  };
}

function taskRun(id: string, createdAt: string): AnySignalReportArtefact {
  return {
    id,
    type: "task_run",
    created_at: createdAt,
    content: { task_id: "t1", product: "signals", type: "research" },
  };
}

describe("selectActivityArtefacts", () => {
  it("keeps only commit and task_run, sorted oldest-first", () => {
    const artefacts: AnySignalReportArtefact[] = [
      taskRun("b", "2026-01-02T00:00:00Z"),
      {
        id: "x",
        type: "note",
        created_at: "2026-01-03T00:00:00Z",
        content: { note: "" },
      },
      commit("a", "2026-01-01T00:00:00Z"),
    ];

    expect(selectActivityArtefacts(artefacts).map((a) => a.id)).toEqual([
      "a",
      "b",
    ]);
  });

  it("returns an empty list when there is no activity", () => {
    const artefacts: AnySignalReportArtefact[] = [
      {
        id: "x",
        type: "note",
        created_at: "2026-01-01T00:00:00Z",
        content: { note: "" },
      },
    ];
    expect(selectActivityArtefacts(artefacts)).toEqual([]);
  });
});

describe("shortSha", () => {
  it("truncates to 12 characters", () => {
    expect(shortSha("abcdef1234567890")).toBe("abcdef123456");
  });
});

describe("taskRunLabel", () => {
  it.each([
    [
      "maps known signals task type to friendly label",
      "signals",
      "repo_selection",
      "Repo selection",
    ],
    [
      "humanizes unknown signals task type",
      "signals",
      "unknown_op",
      "Unknown op",
    ],
    [
      "humanizes identifiers for other products",
      "custom",
      "code-review",
      "Code review",
    ],
  ] as const)("%s", (_desc, product, type, expected) => {
    expect(taskRunLabel({ product, type })).toBe(expected);
  });
});

describe("attributionLabel", () => {
  it.each([
    [
      "prefers first name over email",
      { created_by: { first_name: "Ada", email: "a@b.co" } },
      "Ada",
    ],
    [
      "falls back to email when first name is absent",
      { created_by: { email: "a@b.co" } },
      "a@b.co",
    ],
    ["returns 'agent' when only task_id is set", { task_id: "t1" }, "agent"],
    ["returns null when no attribution is present", {}, null],
  ] as const)("%s", (_desc, input, expected) => {
    expect(attributionLabel(input)).toBe(expected);
  });
});

describe("parseDiffLines", () => {
  it("classifies added, removed, hunk and context lines", () => {
    const lines = parseDiffLines(
      ["@@ -1 +1 @@", "+added", "-removed", " ctx", "+++ b/f", "--- a/f"].join(
        "\n",
      ),
    );
    expect(lines.map((l) => l.kind)).toEqual([
      "hunk",
      "add",
      "del",
      "context",
      "context",
      "context",
    ]);
  });
});
