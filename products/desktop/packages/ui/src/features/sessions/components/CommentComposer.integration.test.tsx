import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CommentComposer } from "./CommentComposer";

describe("CommentComposer", () => {
  it.each(["input-group", "input-group-control", "input-group-addon"])(
    "focuses the editor when clicking the empty %s area",
    async (slot) => {
      const { container } = render(
        <CommentComposer
          value=""
          onValueChange={vi.fn()}
          onSubmit={vi.fn()}
          members={[]}
          placeholder="Comment"
        />,
      );

      const area = container.querySelector(`[data-slot="${slot}"]`);
      expect(area).not.toBeNull();
      fireEvent.click(area as Element);

      await waitFor(() =>
        expect(container.querySelector(".ProseMirror")).toHaveFocus(),
      );
    },
  );

  it.each(["Comment", "Cancel"])(
    "keeps focus on the %s button when clicked",
    async (label) => {
      const onSubmit = vi.fn();
      const onCancel = vi.fn();
      render(
        <CommentComposer
          value="Check this"
          onValueChange={vi.fn()}
          onSubmit={onSubmit}
          onCancel={onCancel}
          members={[]}
          placeholder="Comment"
        />,
      );

      const button = screen.getByRole("button", { name: label });
      button.focus();
      fireEvent.click(button.querySelector("svg") as SVGElement);
      await new Promise(requestAnimationFrame);

      expect(button).toHaveFocus();
      expect(label === "Comment" ? onSubmit : onCancel).toHaveBeenCalledOnce();
    },
  );

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
