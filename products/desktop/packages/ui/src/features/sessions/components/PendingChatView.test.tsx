import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PendingChatView } from "./PendingChatView";

function renderPending(props: { statusText?: string } = {}) {
  render(
    <Theme>
      <PendingChatView
        promptText="Ship the login fix"
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
});
