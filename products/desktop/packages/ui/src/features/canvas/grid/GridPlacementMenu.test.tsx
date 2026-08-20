import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { GridPlacementMenu } from "./GridPlacementMenu";
import type { PlacementActions } from "./placementActions";

const placement: GridPlacement = {
  id: "placement-1",
  status: "live",
  component: "component-1",
  generationTaskId: "task-1",
  x: 0,
  y: 0,
  w: 2,
  h: 2,
};

function actions(): PlacementActions {
  return {
    describe: vi.fn(),
    reset: vi.fn(),
    remove: vi.fn(),
    discuss: vi.fn(),
  };
}

describe("GridPlacementMenu", () => {
  it("keeps the text-only delete action last and asks for confirmation", async () => {
    const cardActions = actions();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <GridPlacementMenu
        placement={placement}
        patching={false}
        actions={cardActions}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Card options" }));
    const menuItems = await screen.findAllByRole("menuitem");

    expect(menuItems.map((item) => item.textContent)).toEqual([
      "View conversation",
      "Delete…",
    ]);
    for (const item of menuItems) {
      expect(item.querySelector("svg")).toBeNull();
    }

    await user.click(menuItems[1]);
    expect(cardActions.remove).not.toHaveBeenCalled();
    expect(
      await screen.findByRole("alertdialog", { name: "Delete card?" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(cardActions.remove).toHaveBeenCalledExactlyOnceWith(placement);
  });

  it("opens the placement task from the menu", async () => {
    const cardActions = actions();
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <GridPlacementMenu
        placement={{ ...placement, status: "generating" }}
        patching={false}
        actions={cardActions}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Card options" }));
    await user.click(
      await screen.findByRole("menuitem", { name: "View progress" }),
    );

    expect(cardActions.discuss).toHaveBeenCalledExactlyOnceWith({
      ...placement,
      status: "generating",
    });
  });

  it("shows only delete when the card has no conversation", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <GridPlacementMenu
        placement={{ ...placement, generationTaskId: null }}
        patching={false}
        actions={actions()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Card options" }));

    expect(
      (await screen.findAllByRole("menuitem")).map((item) => item.textContent),
    ).toEqual(["Delete…"]);
  });
});
