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

function renderCollapsed(
  props: Partial<Parameters<typeof SelectionCommentOverlay>[0]> = {},
) {
  return render(
    <SelectionCommentOverlay
      selection={{
        text: "selected",
        fromLine: 1,
        toLine: 1,
        anchor: { top: 20, endX: 20, bottom: 38 },
      }}
      open
      filePath="report.md"
      onSubmit={vi.fn()}
      onDismiss={vi.fn()}
      {...props}
    />,
  );
}

describe("SelectionCommentOverlay", () => {
  it("keeps the existing add-to-chat action available", () => {
    render(
      <SelectionCommentOverlay
        selection={{
          text: "selected",
          fromLine: 1,
          toLine: 1,
          anchor: { top: 20, endX: 20, bottom: 38 },
        }}
        open
        filePath="report.md"
        onSubmit={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Add to chat")).toBeInTheDocument();
  });

  it("shows no tooltip on the comment action, whose label is already visible", () => {
    renderCollapsed({ actionLabel: "Add comment", showActionText: true });

    fireEvent.focus(screen.getByLabelText("Add comment"));

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.queryByText("Add comment")).not.toBeInTheDocument();
  });

  it("keeps the tooltip on the icon-only action, which has no visible label", () => {
    renderCollapsed();

    fireEvent.focus(screen.getByLabelText("Add to chat"));

    expect(screen.getByRole("tooltip")).toHaveTextContent("Add to chat");
  });
  it("prevents duplicate comment creation while submitting", async () => {
    let resolveSubmit: (() => void) | undefined;
    const onSubmit = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveSubmit = resolve;
        }),
    );
    const onDismiss = vi.fn();
    render(
      <SelectionCommentOverlay
        selection={{
          text: "selected",
          fromLine: 1,
          toLine: 1,
          anchor: { top: 20, endX: 20, bottom: 38 },
        }}
        open
        filePath="report.md"
        onSubmit={onSubmit}
        onDismiss={onDismiss}
        initiallyExpanded
        members={[]}
      />,
    );

    fireEvent.change(screen.getByLabelText("Comment draft"), {
      target: { value: "One comment" },
    });
    const submit = screen.getByLabelText("Comment");
    fireEvent.click(submit);
    fireEvent.click(submit);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveAttribute("aria-disabled", "true");
    expect(submit).toHaveAttribute("aria-busy", "true");
    resolveSubmit?.();
    await waitFor(() => expect(onDismiss).toHaveBeenCalledOnce());
    expect(submit).toHaveAttribute("aria-disabled", "false");
    expect(submit).not.toHaveAttribute("aria-busy");
  });

  it("keeps the draft open when comment creation fails", async () => {
    const onDismiss = vi.fn();
    const onSubmit = vi.fn().mockRejectedValue(new Error("offline"));
    render(
      <SelectionCommentOverlay
        selection={{
          text: "selected",
          fromLine: 1,
          toLine: 1,
          anchor: { top: 20, endX: 20, bottom: 38 },
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
