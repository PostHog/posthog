import type { PanelNode } from "@posthog/core/panels/panelTypes";
import { beforeEach, describe, expect, it } from "vitest";
import { usePanelLayoutStore } from "./panelLayoutStore";

function collectLabels(node: PanelNode): string[] {
  if (node.type === "leaf") return node.content.tabs.map((tab) => tab.label);
  return node.children.flatMap((child) => collectLabels(child));
}

describe("openPostHogObjectTab", () => {
  beforeEach(() => {
    usePanelLayoutStore.setState({ taskLayouts: {} });
  });

  it("gives two long queries sharing a 120-char prefix distinct tabs", () => {
    const prefix = `SELECT event, count() FROM events WHERE ${"x".repeat(120)}`;
    usePanelLayoutStore.getState().initializeTask("task-1");
    usePanelLayoutStore.getState().openPostHogObjectTab("task-1", {
      kind: "hogql",
      id: `${prefix} LIMIT 10`,
      name: "Query A",
    });
    usePanelLayoutStore.getState().openPostHogObjectTab("task-1", {
      kind: "hogql",
      id: `${prefix} LIMIT 20`,
      name: "Query B",
    });

    const layout = usePanelLayoutStore.getState().taskLayouts["task-1"];
    const labels = layout ? collectLabels(layout.panelTree) : [];
    expect(labels).toContain("Query A");
    expect(labels).toContain("Query B");
  });
});
