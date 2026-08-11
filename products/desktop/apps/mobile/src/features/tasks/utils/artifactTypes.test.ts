import type { ArtifactType } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  artifactTypeLabel,
  isDeliverableArtifact,
  selectDeliverableArtifacts,
} from "./artifactTypes";

describe("isDeliverableArtifact", () => {
  it.each<[ArtifactType | undefined, boolean]>([
    ["output", true],
    ["artifact", true],
    ["plan", true],
    ["context", true],
    ["reference", true],
    ["user_attachment", true],
    ["skill_bundle", false],
    [undefined, false],
  ])("treats %s as deliverable: %s", (type, expected) => {
    expect(isDeliverableArtifact({ type: type as ArtifactType })).toBe(
      expected,
    );
  });
});

describe("artifactTypeLabel", () => {
  it.each<[string | undefined, string | null]>([
    ["output", "Output"],
    ["artifact", "Artifact"],
    ["plan", "Plan"],
    ["context", "Context"],
    ["reference", "Reference"],
    ["user_attachment", "Attachment"],
    ["skill_bundle", null],
    ["tree_snapshot", null],
    [undefined, null],
  ])("labels %s as %s", (type, expected) => {
    expect(artifactTypeLabel(type)).toBe(expected);
  });
});

describe("selectDeliverableArtifacts", () => {
  const artifact = (name: string, type: ArtifactType) => ({ name, type });

  it("drops skill bundles but keeps files the user attached", () => {
    const selected = selectDeliverableArtifacts([
      artifact("report.md", "output"),
      artifact("skill.zip", "skill_bundle"),
      artifact("screenshot.png", "user_attachment"),
    ]);

    expect(selected.map((entry) => entry.name)).toEqual([
      "report.md",
      "screenshot.png",
    ]);
  });

  it("groups by type in declaration order, stable within a group", () => {
    const selected = selectDeliverableArtifacts([
      artifact("second-output.txt", "output"),
      artifact("notes.md", "context"),
      artifact("upload.pdf", "user_attachment"),
      artifact("first-output.txt", "output"),
      artifact("plan.md", "plan"),
      artifact("links.md", "reference"),
      artifact("chart.png", "artifact"),
    ]);

    expect(selected.map((entry) => entry.name)).toEqual([
      "plan.md",
      "notes.md",
      "links.md",
      "second-output.txt",
      "first-output.txt",
      "chart.png",
      "upload.pdf",
    ]);
  });

  it("returns an empty list when nothing is a deliverable", () => {
    expect(
      selectDeliverableArtifacts([artifact("s.zip", "skill_bundle")]),
    ).toEqual([]);
  });
});
