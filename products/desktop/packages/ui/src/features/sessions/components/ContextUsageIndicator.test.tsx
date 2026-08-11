import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";
import { Theme } from "@radix-ui/themes";
import { render } from "@testing-library/react";
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

  // The ring carries no text, so the accessible name is the only way the
  // numbers reach a reader — including the "/0 · 0%" an unknown window must
  // never claim, and the cost the flag is supposed to surface.
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
      "Context usage: 25% · $0.42",
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
