import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueuedMessage } from "../../sessionStore";
import { QueuedMessageView } from "./QueuedMessageView";

const MESSAGE: QueuedMessage = {
  id: "q-1",
  content: "queued body",
  queuedAt: 1,
};

function renderView(
  props: Partial<Parameters<typeof QueuedMessageView>[0]> = {},
) {
  const handlers = {
    onSteer: vi.fn(),
    onEdit: vi.fn(),
    onCancelEdit: vi.fn(),
    onRemove: vi.fn(),
  };
  render(
    <Theme>
      <QueuedMessageView message={MESSAGE} {...handlers} {...props} />
    </Theme>,
  );
  return handlers;
}

describe("QueuedMessageView", () => {
  it.each([
    {
      state: "queued",
      isEditing: false,
      visible: ["Steer this message", "Edit queued message"],
      hidden: ["Cancel edit"],
    },
    {
      state: "editing",
      isEditing: true,
      visible: ["Cancel edit"],
      hidden: ["Steer this message", "Edit queued message"],
    },
  ])(
    "shows the $state action set even when every handler is provided",
    ({ isEditing, visible, hidden }) => {
      renderView({ isEditing });

      expect(screen.getByText("queued body")).toBeInTheDocument();
      for (const name of visible) {
        expect(screen.getByRole("button", { name })).toBeInTheDocument();
      }
      for (const name of hidden) {
        expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
      }
      expect(
        screen.getByRole("button", { name: "Discard queued message" }),
      ).toBeInTheDocument();
    },
  );

  it("shows the editing hint while the message is open in the composer", () => {
    renderView({ isEditing: true });
    expect(screen.getByText("Editing in composer")).toBeInTheDocument();
  });

  it.each([
    { name: "Steer this message", handler: "onSteer" as const },
    { name: "Edit queued message", handler: "onEdit" as const },
    { name: "Discard queued message", handler: "onRemove" as const },
  ])(
    "omits the $name button when $handler is not provided",
    ({ name, handler }) => {
      renderView({ [handler]: undefined });
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    },
  );

  it("omits the cancel button when onCancelEdit is not provided", () => {
    renderView({ isEditing: true, onCancelEdit: undefined });
    expect(
      screen.queryByRole("button", { name: "Cancel edit" }),
    ).not.toBeInTheDocument();
  });

  it("wires each visible action to its handler", () => {
    const handlers = renderView();

    fireEvent.click(screen.getByRole("button", { name: "Steer this message" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Edit queued message" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Discard queued message" }),
    );

    expect(handlers.onSteer).toHaveBeenCalledTimes(1);
    expect(handlers.onEdit).toHaveBeenCalledTimes(1);
    expect(handlers.onRemove).toHaveBeenCalledTimes(1);
  });

  it("forwards the drag handle ref to the grip button", () => {
    const dragHandleRef = vi.fn();
    renderView({ dragHandleRef });

    const grip = screen.getByRole("button", { name: "Drag to reorder" });
    expect(grip).toBeInTheDocument();
    expect(dragHandleRef).toHaveBeenCalledWith(grip);
  });
});
