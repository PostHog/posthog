import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
        aria-label="Comment draft"
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
      />
      {children}
    </div>
  ),
}));

import { SelectionCommentOverlay } from "./SelectionCommentOverlay";

describe("SelectionCommentOverlay", () => {
  it("keeps the draft open when comment creation fails", async () => {
    const onDismiss = vi.fn();
    const onSubmit = vi.fn().mockRejectedValue(new Error("offline"));
    render(
      <SelectionCommentOverlay
        selection={{
          text: "selected",
          fromLine: 1,
          toLine: 1,
          anchor: { top: 20, left: 20 },
        }}
        open
        filePath="report.md"
        onSubmit={onSubmit}
        onDismiss={onDismiss}
        initiallyExpanded
        members={[]}
      />,
    );

    const editor = screen.getByLabelText("Comment draft");
    fireEvent.change(editor, { target: { value: "Keep this draft" } });
    fireEvent.click(screen.getByLabelText("Comment"));

    await waitFor(() => expect(onSubmit).toHaveBeenCalled());
    expect(editor).toHaveValue("Keep this draft");
    expect(onDismiss).not.toHaveBeenCalled();
  });
});
