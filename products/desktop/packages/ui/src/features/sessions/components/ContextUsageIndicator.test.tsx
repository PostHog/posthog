import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContextUsageIndicator } from "./ContextUsageIndicator";

const flagState = vi.hoisted(() => ({ enabled: false }));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => flagState.enabled,
}));

beforeEach(() => {
  flagState.enabled = false;
});

function usage(overrides?: Partial<ContextUsage>): ContextUsage {
  return {
    used: 50_000,
    size: 200_000,
    percentage: 25,
    cost: null,
    breakdown: null,
    ...overrides,
  };
}

describe("ContextUsageIndicator", () => {
  it("renders nothing when usage is null", () => {
    const { container } = render(
      <Theme>
        <ContextUsageIndicator usage={null} />
      </Theme>,
    );
    expect(container.querySelector("button")).toBeNull();
  });

  // The ring carries no text, so the accessible name is the only way the token
  // numbers reach a reader — including the "/0 · 0%" an unknown window must
  // never claim. Cost is deliberately absent: it renders as visible text.
  it.each([
    ["a known window", {}, false, "Context usage: 25%"],
    [
      "an unknown window (size 0)",
      { used: 50_000, size: 0, percentage: 0 },
      false,
      "Context usage: 50K tokens",
    ],
    [
      "cost enabled",
      { cost: { amount: 0.42, currency: "USD" } },
      true,
      "Context usage: 25%",
    ],
  ])("names itself for %s", (_case, overrides, costEnabled, expected) => {
    flagState.enabled = costEnabled;
    const { container } = render(
      <Theme>
        <ContextUsageIndicator
          usage={usage(overrides as Partial<ContextUsage>)}
        />
      </Theme>,
    );
    expect(container.querySelector("button")?.getAttribute("aria-label")).toBe(
      expected,
    );
  });

  it("shows the cost as visible text beside the ring", () => {
    flagState.enabled = true;
    render(
      <Theme>
        <ContextUsageIndicator
          usage={usage({ cost: { amount: 0.42, currency: "USD" } })}
        />
      </Theme>,
    );
    // Previously the figure lived only in the aria-label and the popover, so
    // spend was invisible until you opened it.
    expect(screen.getByText("$0.42")).toBeInTheDocument();
  });

  it("renders no cost text when the harness reports none", () => {
    flagState.enabled = true;
    render(
      <Theme>
        <ContextUsageIndicator usage={usage({ cost: null })} />
      </Theme>,
    );
    // Null means "not reported" (codex), not "free" — $0.00 would misstate it.
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();
  });

  it("renders a finite stroke offset at 0% (no NaN/Infinity)", () => {
    const { container } = render(
      <Theme>
        <ContextUsageIndicator
          usage={usage({ used: 0, size: 200_000, percentage: 0 })}
        />
      </Theme>,
    );
    const progress = container.querySelectorAll("circle")[1];
    const offset = Number(progress?.getAttribute("stroke-dashoffset"));
    expect(Number.isFinite(offset)).toBe(true);
  });
});
