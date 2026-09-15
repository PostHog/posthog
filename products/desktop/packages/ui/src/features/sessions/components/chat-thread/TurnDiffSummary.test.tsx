import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatThreadChromeProvider } from "./chatThreadChrome";
import { TurnDiffSummary } from "./TurnDiffSummary";

vi.mock(
  "@posthog/ui/features/sessions/components/session-update/CodePreview",
  () => ({
    CodePreview: ({ filePath }: { filePath?: string }) => (
      <div data-testid="code-preview">{filePath}</div>
    ),
  }),
);

function toolCalls(): Map<string, ToolCall> {
  return new Map([
    [
      "edit-1",
      {
        toolCallId: "edit-1",
        title: "Edit src/app.ts",
        kind: "edit",
        status: "completed",
        content: [
          {
            type: "diff",
            path: "src/app.ts",
            oldText: "const value = 1;",
            newText: "const value = 2;\nconst ready = true;",
          },
        ],
      },
    ],
    [
      "edit-2",
      {
        toolCallId: "edit-2",
        title: "Edit src/view.tsx",
        kind: "edit",
        status: "completed",
        content: [
          {
            type: "diff",
            path: "src/view.tsx",
            oldText: "return null;",
            newText: "return <main />;",
          },
        ],
      },
    ],
  ]);
}

describe("TurnDiffSummary", () => {
  it("shows line totals and keeps the turn diff collapsed until the user opens it", () => {
    render(
      <ChatThreadChromeProvider value>
        <TurnDiffSummary toolCalls={toolCalls()} turnId="turn-1" />
      </ChatThreadChromeProvider>,
    );

    expect(screen.getByText("2 files changed")).toBeInTheDocument();
    expect(screen.getByText("+3")).toBeInTheDocument();
    expect(screen.getByText("-2")).toBeInTheDocument();

    const trigger = screen.getByText("2 files changed").closest("button");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryAllByTestId("code-preview")).toHaveLength(0);

    fireEvent.click(trigger as HTMLButtonElement);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getAllByTestId("code-preview")).toHaveLength(2);
  });
});
