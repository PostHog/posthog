import type { SignalReport } from "@posthog/shared/domain-types";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { mockPush, linkedReport } = vi.hoisted(() => ({
  mockPush: vi.fn(),
  linkedReport: { data: null as SignalReport | null, isLoading: false },
}));

vi.mock("expo-router", () => ({ useRouter: () => ({ push: mockPush }) }));
vi.mock("../hooks/useInboxReports", () => ({
  useInboxReport: () => linkedReport,
}));

import { ArtefactReportLink } from "./ArtefactReportLink";

function render(content: {
  kind: string;
  report_id: string;
  reason?: string | null;
}) {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(createElement(ArtefactReportLink, { content }));
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
  return strings.join(" ");
}

describe("ArtefactReportLink", () => {
  beforeEach(() => {
    mockPush.mockReset();
    linkedReport.data = null;
    linkedReport.isLoading = false;
  });

  it("shows the relation label and the reason", () => {
    const output = visibleText(
      render({ kind: "part_of", report_id: "r2", reason: "Same rollout" }),
    );
    expect(output).toContain("Part of");
    expect(output).toContain("Same rollout");
  });

  it("opens the linked report when pressed", () => {
    const renderer = render({ kind: "part_of", report_id: "r2" });
    act(() => {
      renderer.root
        .findAll((node) => typeof node.props.onPress === "function")[0]
        .props.onPress();
    });
    expect(mockPush).toHaveBeenCalledWith("/inbox/r2");
  });
});
