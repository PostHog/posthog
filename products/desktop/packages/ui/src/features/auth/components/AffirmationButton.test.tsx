import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AffirmationButton } from "./AffirmationButton";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AffirmationButton", () => {
  it.each([
    { roll: 0, affirmation: "You don't need help. You are enough." },
    {
      roll: 0.99,
      affirmation: "Somewhere out there, someone believes in you.",
    },
  ])(
    "shows a random affirmation on the first click (roll $roll)",
    async ({ roll, affirmation }) => {
      vi.spyOn(Math, "random").mockReturnValue(roll);
      const onOpenSupport = vi.fn();
      const user = userEvent.setup();
      render(<AffirmationButton onOpenSupport={onOpenSupport} />);

      await user.click(screen.getByRole("button", { name: /need support\?/i }));

      expect(onOpenSupport).not.toHaveBeenCalled();
      expect(screen.getByText(affirmation)).toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: /get support/i }));

      expect(onOpenSupport).toHaveBeenCalledOnce();
    },
  );
});
