import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AffirmationButton } from "./AffirmationButton";

describe("AffirmationButton", () => {
  it("shows an affirmation on the first click and opens support on the second", async () => {
    const onOpenSupport = vi.fn();
    const user = userEvent.setup();
    render(<AffirmationButton onOpenSupport={onOpenSupport} />);

    await user.click(screen.getByRole("button", { name: /need support\?/i }));

    expect(onOpenSupport).not.toHaveBeenCalled();
    expect(
      screen.getByText("You don't need help. You are enough."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /get support/i }));

    expect(onOpenSupport).toHaveBeenCalledOnce();
  });
});
