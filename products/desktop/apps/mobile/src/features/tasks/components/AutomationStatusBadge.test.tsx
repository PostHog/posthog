import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it } from "vitest";
import { AutomationStatusBadge } from "./AutomationStatusBadge";

describe("AutomationStatusBadge", () => {
  it("does not render a running chip for active automation runs", () => {
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(AutomationStatusBadge, {
          enabled: true,
          lastRunStatus: "running",
          lastTaskRunStatus: "in_progress",
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const output = JSON.stringify(renderer.toJSON());

    expect(output).toContain("Enabled");
    expect(output).not.toContain("Running");
  });

  it("still renders non-running run states", () => {
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(AutomationStatusBadge, {
          enabled: true,
          lastRunStatus: "success",
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    expect(JSON.stringify(renderer.toJSON())).toContain("Success");
  });
});
