import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScoutWriteAccessSection } from "./ScoutWriteAccessSection";

const CONFIG: ScoutConfig = {
  id: "config-1",
  skill_name: "signals-scout-hygiene",
  enabled: true,
  emit: true,
  run_interval_minutes: 1440,
  run_cron_schedule: null,
  write_scopes: [],
  last_run_at: null,
  created_at: "2026-07-21T12:00:00Z",
};

function renderSection(config: Partial<ScoutConfig>) {
  const onUpdate = vi.fn();
  render(
    <ScoutWriteAccessSection
      config={{ ...CONFIG, ...config }}
      onUpdate={onUpdate}
    />,
  );
  return onUpdate;
}

function heldSummary(): string {
  return (
    document.querySelector('[data-attr="scout-write-access-held"]')
      ?.textContent ?? ""
  );
}

describe("ScoutWriteAccessSection", () => {
  it.each([
    ["a live agent", true],
    // A dry run holds no grant, so a live-looking summary promises writes the next run cannot make.
    ["a dry-run agent", false],
  ])("names what the agent holds, for %s", (_name, emit) => {
    renderSection({ emit, write_scopes: ["llm_skill:write"] });

    expect(heldSummary()).toContain("Skills");
    expect(heldSummary()).not.toContain("Read only");
    expect(heldSummary().includes("Inactive during dry run")).toBe(!emit);
  });

  it.each([
    ["a read-only agent", []],
    // A stored scope with no switch must not be resent: the API rejects the whole update.
    ["an agent holding a scope the picker no longer offers", ["cohort:write"]],
  ])(
    "stages a grant and saves only on the save button, for %s",
    (_name, stored) => {
      const onUpdate = renderSection({ write_scopes: stored });

      fireEvent.click(
        screen.getByLabelText("Let this agent write warehouse tables"),
      );
      expect(onUpdate).not.toHaveBeenCalled();

      fireEvent.click(screen.getByText("Save write access"));
      expect(onUpdate).toHaveBeenCalledWith("config-1", {
        write_scopes: ["warehouse_table:write"],
      });
    },
  );

  it("saves an empty grant when every scope is cleared", () => {
    const onUpdate = renderSection({ write_scopes: ["warehouse_view:write"] });

    fireEvent.click(
      screen.getByLabelText("Let this agent write warehouse views"),
    );
    fireEvent.click(screen.getByText("Save write access"));

    expect(onUpdate).toHaveBeenCalledWith("config-1", { write_scopes: [] });
  });

  it("cannot save a grant nobody changed", () => {
    renderSection({ write_scopes: ["insight:write"] });

    expect(screen.getByText("Save write access")).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });
});
