import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CommentComposer } from "./CommentComposer";

describe("CommentComposer submission", () => {
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
