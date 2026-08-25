import type { AutoresearchDraftConfig } from "@posthog/core/autoresearch/schemas";
import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AutoresearchComposerControls } from "./AutoresearchComposerControls";

const draft: AutoresearchDraftConfig = {
  direction: "maximize",
  targetValue: null,
  maxIterations: 10,
  implementModel: "model-a",
  measureModel: "model-a",
  implementEffort: "medium",
  measureEffort: "medium",
};

function renderControls(
  overrides: Partial<AutoresearchDraftConfig> = {},
  onChange = vi.fn(),
) {
  render(
    <Theme>
      <AutoresearchComposerControls
        draft={{ ...draft, ...overrides }}
        modelOptions={[{ value: "model-a", label: "Model A" }]}
        effortOptions={[{ value: "medium", label: "Medium" }]}
        onChange={onChange}
        onExit={vi.fn()}
      />
    </Theme>,
  );
  return onChange;
}

describe("AutoresearchComposerControls", () => {
  it("explains the workflow without hiding the prompt requirements", () => {
    renderControls();

    expect(screen.getByText("Autoresearch")).toBeVisible();
    expect(
      screen.getByText(
        /modifies the codebase and evaluates a user defined metric/i,
      ),
    ).toBeVisible();
    expect(screen.getByText("Include in your prompt")).toBeVisible();
    expect(screen.getByText("The metric to optimize")).toBeVisible();
    expect(
      screen.getByText("The command or steps to measure it"),
    ).toBeVisible();
    expect(
      screen.getByText("Constraints the agent must preserve"),
    ).toBeVisible();
  });

  it("updates the attempt limit from the primary setup", () => {
    const onChange = renderControls();

    fireEvent.change(screen.getByLabelText("Maximum attempts"), {
      target: { value: "6" },
    });

    expect(onChange).toHaveBeenCalledWith({ maxIterations: 6 });
  });

  it("shows both metric directions and updates the selected direction", async () => {
    const user = userEvent.setup();
    const onChange = renderControls();

    expect(screen.getByRole("radio", { name: "Increase" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "Decrease" })).toBeVisible();

    await user.click(screen.getByRole("radio", { name: "Decrease" }));

    expect(onChange).toHaveBeenCalledWith({ direction: "minimize" });
  });

  it("keeps target configuration behind advanced settings", async () => {
    const user = userEvent.setup();
    const onChange = renderControls();

    expect(
      screen.queryByLabelText("Target metric value to stop at"),
    ).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: "Advanced autoresearch settings" }),
    );
    fireEvent.change(screen.getByLabelText("Target metric value to stop at"), {
      target: { value: "95" },
    });

    expect(onChange).toHaveBeenCalledWith({ targetValue: 95 });
  });

  it("explains the autoresearch loop in a help dialog", async () => {
    const user = userEvent.setup();
    renderControls();

    await user.click(
      screen.getByRole("button", { name: "What is autoresearch?" }),
    );

    expect(
      screen.getByRole("heading", { name: "What is autoresearch?" }),
    ).toBeVisible();
    expect(screen.getByText("Measure a baseline")).toBeVisible();
    expect(screen.getByText("Try an improvement")).toBeVisible();
    expect(screen.getByText("Repeat until it stops")).toBeVisible();
    expect(
      screen.getByRole("img", {
        name: /Example autoresearch metric improving over five attempts/,
      }),
    ).toBeVisible();
    expect(screen.getByText("55 ms")).toBeVisible();
    expect(screen.getByText("Example prompt")).toBeVisible();
    expect(screen.getByRole("radio", { name: "Performance" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "Bundle size" })).toBeVisible();
    expect(
      screen.getByRole("radio", { name: "Test reliability" }),
    ).toBeVisible();
    expect(screen.getByText(/pnpm bench:search/)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Send feedback or report a bug" }),
    ).toBeVisible();
    expect(screen.getByText("autoresearch@posthog.com")).toBeVisible();
  });
});
