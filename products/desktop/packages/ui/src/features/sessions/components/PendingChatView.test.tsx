import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PendingChatView } from "./PendingChatView";

function renderPending(
  props: {
    content?: string;
    attachments?: { id: string; label: string }[];
    statusText?: string;
  } = {},
) {
  render(
    <Theme>
      <PendingChatView
        content={props.content ?? "Ship the login fix"}
        attachments={props.attachments}
        statusText={props.statusText}
      />
    </Theme>,
  );
}

describe("PendingChatView", () => {
  it("renders the prompt as a chat message with the default status", () => {
    renderPending();
    expect(screen.getByText("Ship the login fix")).toBeInTheDocument();
    expect(screen.getByText("Starting task...")).toBeInTheDocument();
  });

  it("shows the live run status in place of the default line", () => {
    renderPending({ statusText: "Starting the sandbox…" });
    expect(screen.getByText("Starting the sandbox…")).toBeInTheDocument();
    expect(screen.queryByText("Starting task...")).not.toBeInTheDocument();
  });

  it("renders file mentions as chips so the bubble matches the live transcript", () => {
    renderPending({
      content: 'fix <file path="src/a.ts" />',
    });
    expect(screen.getByText("src/a.ts")).toBeInTheDocument();
    expect(screen.queryByText("fix @src/a.ts")).not.toBeInTheDocument();
  });

  it("hides attachment chips when the content already carries file mentions", () => {
    renderPending({
      content: 'run this <file path="src/a.ts" />',
      attachments: [{ id: "src/a.ts", label: "src/a.ts" }],
    });
    expect(screen.getByText("src/a.ts")).toBeInTheDocument();
    // The attachment would render the same label a second time.
    expect(screen.getAllByText("src/a.ts")).toHaveLength(1);
  });

  it("shows attachments for plain content without file mentions", () => {
    renderPending({
      content: "summarize this",
      attachments: [{ id: "notes.txt", label: "notes.txt" }],
    });
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
  });
});
