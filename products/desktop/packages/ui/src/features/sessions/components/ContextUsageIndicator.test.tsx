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

  it("renders the compact used/size label, percentage, and aria-label", () => {
    render(
      <Theme>
        <ContextUsageIndicator usage={usage()} />
      </Theme>,
    );
    expect(screen.getByText(/50K\/200K · 25%/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Context usage: 25%" }),
    ).toBeInTheDocument();
  });

  it("shows only the token count when the context window is unknown (size 0)", () => {
    render(
      <Theme>
        <ContextUsageIndicator
          usage={usage({ used: 50_000, size: 0, percentage: 0 })}
        />
      </Theme>,
    );
    // No misleading "/0 · 0%" — just the used tokens.
    expect(screen.getByText("50K")).toBeInTheDocument();
    expect(screen.queryByText(/\/0/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Context usage: 50K tokens" }),
    ).toBeInTheDocument();
  });

  it("appends the estimated cost to the label when the flag is enabled", () => {
    flagState.enabled = true;
    render(
      <Theme>
        <ContextUsageIndicator
          usage={usage({ cost: { amount: 0.42, currency: "USD" } })}
        />
      </Theme>,
    );
    expect(screen.getByText(/50K\/200K · 25% · \$0\.42/)).toBeInTheDocument();
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
    expect(screen.getByText(/0\/200K · 0%/)).toBeInTheDocument();
  });
});
