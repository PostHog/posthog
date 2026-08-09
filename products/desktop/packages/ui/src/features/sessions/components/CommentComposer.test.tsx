import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/canvas/components/MentionComposer", () => ({
  MentionComposer: ({
    value,
    onValueChange,
    onSubmit,
    children,
  }: {
    value: string;
    onValueChange: (value: string) => void;
    onSubmit: () => void;
    children: ReactNode;
  }) => (
    <div>
      <textarea
        aria-label="Comment"
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
      />
      <button
        type="button"
        onClick={() => {
          onValueChange("Fresh comment");
          onSubmit();
        }}
      >
        Type and submit
      </button>
      {children}
    </div>
  ),
}));

import { MentionAvailabilityProvider } from "@posthog/ui/features/sessions/mentionAvailability";
import { CommentComposer } from "./CommentComposer";

describe("CommentComposer", () => {
  it("submits an editor update before the controlled value rerenders", () => {
    const onSubmit = vi.fn();
    render(
      <Theme>
        <CommentComposer
          value=""
          onValueChange={vi.fn()}
          onSubmit={onSubmit}
          members={[]}
          placeholder="Comment"
        />
      </Theme>,
    );

    fireEvent.click(screen.getByText("Type and submit"));

    expect(onSubmit).toHaveBeenCalledWith("Fresh comment", []);
  });

  it("explains that mentions are unavailable in the private space", () => {
    const onValueChange = vi.fn();
    render(
      <Theme>
        <MentionAvailabilityProvider disabledReason="Mentions aren’t available in #me.">
          <CommentComposer
            value="@"
            onValueChange={onValueChange}
            onSubmit={vi.fn()}
            members={[]}
            placeholder="Comment"
          />
        </MentionAvailabilityProvider>
      </Theme>,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "Mentions aren’t available in #me.",
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Comment" }), {
      target: { value: "private note" },
    });
    expect(onValueChange).toHaveBeenCalledWith("private note");
  });
});
