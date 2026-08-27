import { describe, expect, it } from "vitest";
import {
  findHandoffArtifactId,
  newestHandoffArtifactId,
} from "./flowHandoffArtifacts";

describe("flow handoff artifacts", () => {
  const artifacts = [
    {
      id: "v1",
      name: "flow-step-1-plan.md",
      type: "output",
      uploaded_at: "2026-08-27T10:00:00Z",
    },
    {
      id: "v2",
      name: "flow-step-1-plan.md",
      type: "output",
      uploaded_at: "2026-08-27T11:00:00Z",
    },
    {
      id: "other",
      name: "flow-step-2-build.md",
      type: "output",
      uploaded_at: "2026-08-27T12:00:00Z",
    },
  ];

  it.each([
    [1, "v1"],
    [2, "v2"],
  ])("resolves version %i of the document", (version, expected) => {
    expect(
      findHandoffArtifactId(artifacts, "flow-step-1-plan.md", version),
    ).toBe(expected);
  });

  it("reports a version that is not stored yet", () => {
    expect(findHandoffArtifactId(artifacts, "flow-step-1-plan.md", 3)).toBe(
      null,
    );
  });

  it("reads the newest version of the document", () => {
    expect(newestHandoffArtifactId(artifacts, "flow-step-1-plan.md")).toBe(
      "v2",
    );
  });
});
