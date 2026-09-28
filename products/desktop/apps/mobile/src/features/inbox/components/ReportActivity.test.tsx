import type { AnySignalReportArtefact } from "@posthog/shared/domain-types";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

vi.mock("./ArtefactCommit", () => ({ ArtefactCommit: () => null }));
vi.mock("./ArtefactTaskRun", () => ({ ArtefactTaskRun: () => null }));

import { ReportActivity } from "./ReportActivity";

const commit: AnySignalReportArtefact = {
  id: "a1",
  type: "commit",
  created_at: "2026-01-01T00:00:00Z",
  content: {
    repository: "posthog/posthog",
    branch: "main",
    commit_sha: "abcdef1234567890",
    message: "fix",
  },
};

function render(props: {
  artefacts?: AnySignalReportArtefact[];
  collapsedNoteCount?: number;
}) {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(
      createElement(ReportActivity, {
        reportId: "r1",
        artefacts: props.artefacts ?? [],
        collapsedNoteCount: props.collapsedNoteCount,
      }),
    );
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function visibleText(renderer: ReturnType<typeof create>): string {
  const strings: string[] = [];
  const walk = (node: unknown): void => {
    if (typeof node === "string") strings.push(node);
    else if (Array.isArray(node)) for (const child of node) walk(child);
    else if (node && typeof node === "object" && "children" in node) {
      walk((node as { children: unknown }).children);
    }
  };
  walk(renderer.toJSON());
  return strings.join("");
}

describe("ReportActivity", () => {
  it("renders nothing when there are no artefacts and no confirmations", () => {
    expect(render({}).toJSON()).toBeNull();
  });

  it("renders the artefact count without a confirmation suffix", () => {
    const output = visibleText(render({ artefacts: [commit] }));
    expect(output).toContain("Activity");
    expect(output).toContain("(1)");
    expect(output).not.toContain("confirmation");
    expect(output).not.toContain("Corroborated");
  });

  it.each([
    [1, "1 confirmation", "Corroborated 1 more time by a scout"],
    [3, "3 confirmations", "Corroborated 3 more times by a scout"],
  ] as const)(
    "shows collapsed confirmations with the right singular or plural (%s)",
    (count, headerSuffix, line) => {
      const output = visibleText(render({ collapsedNoteCount: count }));
      expect(output).toContain(`(0) · ${headerSuffix}`);
      expect(output).toContain(`${line}, with nothing new to add.`);
    },
  );
});
