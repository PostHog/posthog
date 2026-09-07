import type { AutoresearchIteration } from "@posthog/core/autoresearch/schemas";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { IterationsTable } from "./IterationsTable";

const iteration: AutoresearchIteration = {
  index: 1,
  value: 90,
  bestValue: 90,
  delta: null,
  summary:
    "Reworked serialization to avoid repeatedly copying the full payload during every measurement pass.",
  hypothesis: null,
  plan: null,
  approach: "serialization",
  at: 1,
};

describe("IterationsTable", () => {
  it("expands long change summaries", async () => {
    const user = userEvent.setup();
    const summary = iteration.summary ?? "";
    render(
      <Theme>
        <IterationsTable
          iterations={[iteration]}
          direction="minimize"
          unit="MB"
        />
      </Theme>,
    );

    const trigger = screen.getByLabelText("Expand change details");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByText(summary, { selector: "div" }),
    ).not.toBeInTheDocument();

    await user.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(summary, { selector: "div" })).toBeVisible();
  });
});
