import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import type { ScoutAttention } from "@posthog/core/scouts/scoutPresentation";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ScoutAttentionSummary } from "./ScoutAttentionSummary";

function makeItem(
  id: string,
  skillName: string,
  overrides: Partial<ScoutAttention> = {},
): ScoutAttention {
  return {
    kind: "auto_paused",
    detail: "Nobody acted on its signals.",
    config: {
      id,
      skill_name: skillName,
      enabled: false,
      emit: true,
      run_interval_minutes: 60,
      last_run_at: null,
      created_at: "2026-06-01T00:00:00Z",
    } as ScoutConfig,
    ...overrides,
  };
}

describe("ScoutAttentionSummary", () => {
  it("names the agents behind the count once opened", async () => {
    render(
      <ScoutAttentionSummary
        items={[
          makeItem("a", "signals-scout-error-tracking"),
          makeItem("b", "signals-scout-surveys", {
            kind: "pausing_soon",
            detail: "It stopped sending signals. PostHog pauses it soon.",
          }),
        ]}
      />,
    );

    const trigger = screen.getByRole("button", {
      name: "1 auto-paused · 1 pausing soon",
    });
    await userEvent.hover(trigger);

    expect(await screen.findByText("Error tracking")).toBeInTheDocument();
    expect(
      screen.getByText("Nobody acted on its signals."),
    ).toBeInTheDocument();
    expect(screen.getByText("Surveys")).toBeInTheDocument();
  });

  it("renders nothing when no agent waits on a decision", () => {
    const { container } = render(<ScoutAttentionSummary items={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
