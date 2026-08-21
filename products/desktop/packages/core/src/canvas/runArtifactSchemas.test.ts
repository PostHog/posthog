import { describe, expect, it } from "vitest";
import {
  getPostHogObjectArtifactMetadata,
  groupRunArtifactVersions,
  OUTPUT_ARTIFACT_TYPES,
  parseRunArtifacts,
} from "./runArtifactSchemas";

describe("parseRunArtifacts", () => {
  it.each([
    { name: "undefined", raw: undefined },
    { name: "null", raw: null },
    { name: "an object", raw: { artifacts: [] } },
    { name: "a string", raw: "output" },
  ])("reads $name as no artifacts", ({ raw }) => {
    expect(parseRunArtifacts(raw, OUTPUT_ARTIFACT_TYPES)).toEqual([]);
  });

  // A run's manifest mixes deliverables with plumbing nobody asked to see.
  it("keeps only the requested types", () => {
    const outputs = parseRunArtifacts(
      [
        { id: "a", type: "output", name: "report.md" },
        { id: "b", type: "user_attachment", name: "clipboard.png" },
        { id: "c", type: "skill_bundle", name: "skills.zip" },
      ],
      OUTPUT_ARTIFACT_TYPES,
    );
    expect(outputs).toEqual([{ id: "a", type: "output", name: "report.md" }]);
  });

  it("reads the size and upload time the row renders", () => {
    const artifact = {
      id: "a",
      type: "output",
      name: "report.md",
      size: 16861,
      content_type: "text/markdown",
      uploaded_at: "2026-07-27T08:27:26.896719+00:00",
      uploaded_by: "user" as const,
      uploaded_by_user_id: 42,
    };
    expect(parseRunArtifacts([artifact], OUTPUT_ARTIFACT_TYPES)).toEqual([
      artifact,
    ]);
  });

  it("keeps an artifact that omits the optional fields", () => {
    expect(
      parseRunArtifacts([{ type: "output" }], OUTPUT_ARTIFACT_TYPES),
    ).toEqual([{ type: "output" }]);
  });

  // One bad entry shouldn't take the Artifacts tab down with it.
  it("drops entries that don't match the shape", () => {
    const outputs = parseRunArtifacts(
      [
        { id: 42, type: "output" },
        null,
        "not an object",
        { type: "output", storage_path: "runs/1/report.md" },
      ],
      OUTPUT_ARTIFACT_TYPES,
    );
    expect(outputs).toEqual([
      { type: "output", storage_path: "runs/1/report.md" },
    ]);
  });

  it("ignores an artifact with no type", () => {
    expect(
      parseRunArtifacts([{ id: "a", name: "mystery" }], OUTPUT_ARTIFACT_TYPES),
    ).toEqual([]);
  });
});

describe("getPostHogObjectArtifactMetadata", () => {
  it("accepts PostHog references without file storage fields", () => {
    expect(
      getPostHogObjectArtifactMetadata({
        type: "reference",
        metadata: {
          reference_type: "posthog_object",
          object_kind: "insight",
          object_id: "9pQx3",
          source_message_ids: ["turn-1"],
          occurrence_count: 1,
        },
      }),
    ).toEqual({
      reference_type: "posthog_object",
      object_kind: "insight",
      object_id: "9pQx3",
      source_message_ids: ["turn-1"],
      occurrence_count: 1,
    });
  });
});

describe("groupRunArtifactVersions", () => {
  it("collapses re-uploads of a name into one newest-first group", () => {
    const groups = groupRunArtifactVersions([
      { id: "a", name: "report.md", uploaded_at: "2026-07-27T08:00:00Z" },
      { id: "b", name: "chart.png", uploaded_at: "2026-07-27T08:30:00Z" },
      { id: "c", name: "report.md", uploaded_at: "2026-07-27T09:00:00Z" },
    ]);

    expect(groups.map((group) => group.name)).toEqual([
      "report.md",
      "chart.png",
    ]);
    expect(groups[0]?.versions.map((version) => version.id)).toEqual([
      "c",
      "a",
    ]);
    expect(groups[0]?.latest.id).toBe("c");
  });

  // A file is only gone once every upload of it is dismissed — otherwise
  // dismissing the current version would resurrect the one it replaced.
  it.each([
    { name: "no version", dismissedIds: [] as string[], dismissed: false },
    { name: "only the newest version", dismissedIds: ["b"], dismissed: false },
    { name: "every version", dismissedIds: ["a", "b"], dismissed: true },
  ])(
    "reports dismissed as $dismissed when $name is",
    ({ dismissedIds, dismissed }) => {
      const groups = groupRunArtifactVersions(
        [
          { id: "a", name: "report.md", uploaded_at: "2026-07-27T08:00:00Z" },
          { id: "b", name: "report.md", uploaded_at: "2026-07-27T09:00:00Z" },
        ].map((artifact) => ({
          ...artifact,
          dismissed_at: dismissedIds.includes(artifact.id)
            ? "2026-07-27T10:00:00Z"
            : null,
        })),
      );

      expect(groups[0]?.dismissed).toBe(dismissed);
    },
  );

  it("skips artifacts with no name", () => {
    expect(
      groupRunArtifactVersions([{ uploaded_at: "2026-07-27T08:00:00Z" }]),
    ).toEqual([]);
  });
});
