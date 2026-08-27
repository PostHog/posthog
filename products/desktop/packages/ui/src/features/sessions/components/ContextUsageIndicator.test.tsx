import { TASK_COST_VISIBLE_FLAG } from "@posthog/shared";
import type { ContextUsage } from "@posthog/ui/features/sessions/hooks/useContextUsage";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContextUsageIndicator } from "./ContextUsageIndicator";

const flagState = vi.hoisted(() => ({ cost: false, costVisible: false }));
const taskUsageState = vi.hoisted(() => ({
  data: undefined as
    | {
        token_cost_usd: number;
        compute_cost_usd: number;
        total_cost_usd: number;
      }
    | undefined,
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: (key: string) =>
    key === TASK_COST_VISIBLE_FLAG ? flagState.costVisible : flagState.cost,
}));
vi.mock("@posthog/ui/features/sessions/hooks/useTaskUsage", () => ({
  useTaskUsage: () => taskUsageState,
}));

function enableCost(costVisible = false) {
  flagState.cost = true;
  flagState.costVisible = costVisible;
  taskUsageState.data = {
    token_cost_usd: 0.4,
    compute_cost_usd: 0.02,
    total_cost_usd: 0.42,
  };
}

beforeEach(() => {
  flagState.cost = false;
  flagState.costVisible = false;
  taskUsageState.data = undefined;
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
  // never claim, and the cost while it has no text of its own.
  it.each([
    ["a known window", {}, false, false, "Context usage: 25%"],
    [
      "an unknown window (size 0)",
      { used: 50_000, size: 0, percentage: 0 },
      false,
      false,
      "Context usage: 50K tokens",
    ],
    ["cost enabled", {}, true, false, "Context usage: 25% · $0.42"],
    ["cost shown as text", {}, true, true, "Context usage: 25%"],
  ])(
    "names itself for %s",
    (_case, overrides, costEnabled, costVisible, expected) => {
      if (costEnabled) enableCost(costVisible);
      const { container } = render(
        <Theme>
          <ContextUsageIndicator
            usage={usage(overrides as Partial<ContextUsage>)}
            taskId="task-1"
          />
        </Theme>,
      );
      expect(
        container.querySelector("button")?.getAttribute("aria-label"),
      ).toBe(expected);
    },
  );

  it("shows the cost beside the ring once the visible flag is on", () => {
    enableCost(true);
    render(
      <Theme>
        <ContextUsageIndicator usage={usage()} taskId="task-1" />
      </Theme>,
    );
    expect(screen.getByText("$0.42")).toBeInTheDocument();
  });

  it("keeps the cost in the popover while the visible flag is off", () => {
    enableCost();
    render(
      <Theme>
        <ContextUsageIndicator usage={usage()} taskId="task-1" />
      </Theme>,
    );
    expect(screen.queryByText("$0.42")).not.toBeInTheDocument();
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
