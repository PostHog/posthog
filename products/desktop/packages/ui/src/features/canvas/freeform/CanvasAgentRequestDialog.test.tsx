import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CanvasAgentRequestDialog } from "./CanvasAgentRequestDialog";

describe("CanvasAgentRequestDialog", () => {
  it("requires an explicit choice", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();

    render(
      <CanvasAgentRequestDialog
        prompt="Update the chart"
        loading={false}
        onCancel={onCancel}
        onConfirm={vi.fn()}
      />,
    );

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(onCancel).not.toHaveBeenCalled();

    await user.click(screen.getByText("Cancel"));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
