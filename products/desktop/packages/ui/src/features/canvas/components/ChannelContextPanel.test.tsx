import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

// Radix's ScrollArea observes resizes; jsdom lacks ResizeObserver.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

import { ChannelContextPanel } from "./ChannelContextPanel";

function renderPanel(
  props?: Partial<Parameters<typeof ChannelContextPanel>[0]>,
) {
  const onClose = props?.onClose ?? vi.fn();
  render(
    <Theme>
      <ChannelContextPanel
        channelName={props?.channelName ?? "project-bluebird"}
        body={props?.body ?? "# Heading\n\nSome **context** body."}
        onClose={onClose}
      />
    </Theme>,
  );
  return onClose;
}

describe("ChannelContextPanel", () => {
  it.each([
    {
      channelName: "project-bluebird",
      expectedTitle: "project-bluebird CONTEXT.md",
    },
    { channelName: undefined, expectedTitle: "CONTEXT.md" },
  ])(
    "renders title '$expectedTitle' for channelName=$channelName",
    ({ channelName, expectedTitle }) => {
      render(
        <Theme>
          <ChannelContextPanel
            channelName={channelName}
            body="body"
            onClose={vi.fn()}
          />
        </Theme>,
      );
      expect(screen.getByText(expectedTitle)).toBeInTheDocument();
    },
  );

  it("renders the markdown body", () => {
    renderPanel();
    expect(screen.getByText("Heading")).toBeInTheDocument();
    expect(screen.getByText("context")).toBeInTheDocument();
  });

  it("calls onClose when the close button is clicked", async () => {
    const user = userEvent.setup();
    const onClose = renderPanel();
    await user.click(
      screen.getByRole("button", { name: "Close CONTEXT.md panel" }),
    );
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
