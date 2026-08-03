import { describe, expect, it } from "vitest";
import { OUTPUT_ARTIFACT_TYPES, parseRunArtifacts } from "./runArtifactSchemas";

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
