import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ channelsLayout: true }));

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => mocks.channelsLayout,
}));
vi.mock("@tanstack/react-router", () => ({
  useRouterState: () => "/website",
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
// Its form reaches for the channel and repository query stacks this file has none of.
vi.mock("@posthog/ui/features/canvas/components/CreateChannelModal", () => ({
  CreateChannelModal: () => null,
}));

import { ChannelsFab } from "./ChannelsFab";

describe("ChannelsFab", () => {
  it.each([
    {
      what: "the channel list, where a new space has no other entry point",
      channelId: undefined,
      shown: true,
    },
    {
      what: "inside a space, where the list leads with its own create row",
      channelId: "channel-1",
      shown: false,
    },
  ])("under the layout it floats over $what", ({ channelId, shown }) => {
    mocks.channelsLayout = true;

    render(
      <Theme>
        <ChannelsFab channelId={channelId} />
      </Theme>,
    );

    expect(screen.queryAllByRole("button", { name: "Create" })).toHaveLength(
      shown ? 1 : 0,
    );
  });

  it("keeps its button inside a channel off the layout", () => {
    mocks.channelsLayout = false;

    render(
      <Theme>
        <ChannelsFab channelId="channel-1" />
      </Theme>,
    );

    expect(screen.getByRole("button", { name: "Create" })).toBeInTheDocument();
  });
});
