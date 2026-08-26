import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TaskRepositoryDialog } from "./TaskRepositoryDialog";

describe("TaskRepositoryDialog", () => {
  it("applies an empty repository selection", async () => {
    const user = userEvent.setup();
    const onApply = vi.fn();

    render(
      <TaskRepositoryDialog
        open
        onOpenChange={vi.fn()}
        cloud
        repositories={["posthog/posthog"]}
        integrationId={7}
        folder=""
        onApply={onApply}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Remove posthog/posthog" }),
    );

    const apply = screen.getByRole("button", { name: "Apply" });
    expect(apply).not.toHaveAttribute("aria-disabled", "true");
    await user.click(apply);

    expect(onApply).toHaveBeenCalledWith({
      repositories: [],
      integrationId: null,
      folder: "",
      saveToSpace: false,
    });
  });
});
