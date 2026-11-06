import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/canvas/components/MentionComposer", () => ({
  MentionComposer: ({
    value,
    onValueChange,
    children,
  }: {
    value: string;
    onValueChange: (value: string) => void;
    children: ReactNode;
  }) => (
    <div>
      <textarea
        aria-label="Comment"
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
      />
      {children}
    </div>
  ),
}));

import { MentionAvailabilityProvider } from "@posthog/ui/features/sessions/mentionAvailability";
import { CommentComposer } from "./CommentComposer";

describe("CommentComposer", () => {
  it("explains that mentions are unavailable in the private space", () => {
    const onValueChange = vi.fn();
    render(
      <Theme>
        <MentionAvailabilityProvider disabledReason="Mentions aren’t available in your personal space.">
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
      "Mentions aren’t available in your personal space.",
    );
    fireEvent.change(screen.getByRole("textbox", { name: "Comment" }), {
      target: { value: "private note" },
    });
    expect(onValueChange).toHaveBeenCalledWith("private note");
  });
});
