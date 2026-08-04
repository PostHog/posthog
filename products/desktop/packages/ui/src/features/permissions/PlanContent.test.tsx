import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { PlanContent } from "./PlanContent";

const PLAN = "# Test plan\n\nShip the fix.";

function renderPlan() {
  return render(
    <Theme>
      <PlanContent id="test-plan" plan={PLAN} />
    </Theme>,
  );
}

describe("PlanContent", () => {
  beforeEach(() => {
    document.querySelectorAll("#fullscreen-portal").forEach((node) => {
      node.remove();
    });
    const portal = document.createElement("div");
    portal.id = "fullscreen-portal";
    document.body.appendChild(portal);
  });

  it("expands into the session fullscreen portal", async () => {
    const user = userEvent.setup();
    renderPlan();

    await user.click(
      screen.getByRole("button", { name: "Expand to fullscreen" }),
    );

    const portal = document.getElementById("fullscreen-portal");
    if (!portal) throw new Error("Fullscreen portal was not rendered");
    expect(portal).toHaveTextContent("Test plan");
    expect(
      within(portal).getByRole("button", { name: "Exit fullscreen" }),
    ).toBeInTheDocument();
  });

  it("exits fullscreen when Escape is pressed", async () => {
    const user = userEvent.setup();
    renderPlan();

    await user.click(
      screen.getByRole("button", { name: "Expand to fullscreen" }),
    );
    fireEvent.keyDown(window, { key: "Escape" });

    expect(
      screen.getByRole("button", { name: "Expand to fullscreen" }),
    ).toBeInTheDocument();
  });
});
