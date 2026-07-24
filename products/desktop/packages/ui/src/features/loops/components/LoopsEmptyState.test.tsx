import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoopsEmptyState } from "./LoopsEmptyState";

describe("LoopsEmptyState", () => {
  it("starts loop creation from the primary CTA", async () => {
    const onCreate = vi.fn();
    render(
      <Theme>
        <LoopsEmptyState onCreate={onCreate} />
      </Theme>,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Create a loop" }),
    );

    expect(onCreate).toHaveBeenCalledOnce();
  });

  it("disables creation when the project reached its loop limit", () => {
    render(
      <Theme>
        <LoopsEmptyState
          onCreate={vi.fn()}
          disabledReason="This project reached its loop limit."
        />
      </Theme>,
    );

    expect(
      screen.getByRole("button", { name: "Create a loop" }),
    ).toBeDisabled();
  });
});
