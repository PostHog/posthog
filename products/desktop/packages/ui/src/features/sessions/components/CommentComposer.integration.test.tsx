import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/canvas/hooks/useCommentEmojis", () => ({
  useCommentEmojis: () => ({ data: [] }),
}));

import { CommentComposer } from "./CommentComposer";

describe("CommentComposer submission", () => {
  it("opens emoji autocomplete from a shortcode and inserts the selected emoji", async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    const { container } = render(
      <CommentComposer
        value=""
        onValueChange={onValueChange}
        onSubmit={vi.fn()}
        members={[]}
        placeholder="Comment"
      />,
    );
    const editor = container.querySelector(".ProseMirror");
    expect(editor).not.toBeNull();

    (editor as HTMLElement).focus();
    await user.keyboard(":wav");
    await user.click(await screen.findByLabelText(":waving_hand:"));

    expect(onValueChange).toHaveBeenLastCalledWith("👋");
  });

  it.each(["enter", "send"] as const)(
    "submits the current comment with %s",
    (input) => {
      const onSubmit = vi.fn();
      const { container } = render(
        <CommentComposer
          value="Check this"
          onValueChange={vi.fn()}
          onSubmit={onSubmit}
          members={[]}
          placeholder="Comment"
        />,
      );

      if (input === "enter") {
        const editor = container.querySelector(".ProseMirror");
        expect(editor).not.toBeNull();
        fireEvent.keyDown(editor as Element, { key: "Enter" });
      } else {
        fireEvent.click(screen.getByLabelText("Comment"));
      }

      expect(onSubmit).toHaveBeenCalledWith("Check this", []);
    },
  );
});
