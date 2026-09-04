import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  channels: [] as {
    id: string;
    name: string;
    channelType: "public" | "personal";
  }[],
  isLoading: false,
  toggleStar: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: mocks.channels, isLoading: mocks.isLoading }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelStars", () => ({
  useChannelStarToggle: () => ({
    isStarred: false,
    toggleStar: mocks.toggleStar,
  }),
}));

import { useChannelPaneStore } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { ChannelBackRow } from "./ChannelBackRow";

const ENG = {
  id: "eng-id",
  name: "engineering",
  channelType: "public" as const,
};
const ME = { id: "me-id", name: "me", channelType: "personal" as const };

function renderRow(channelId: string) {
  return render(
    <Theme>
      <ChannelBackRow channelId={channelId} />
    </Theme>,
  );
}

describe("ChannelBackRow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.channels = [ME, ENG];
    mocks.isLoading = false;
    useChannelPaneStore.setState({
      pane: "channel",
      animateTransition: false,
    });
  });

  it("names the channel you're in", () => {
    renderRow(ENG.id);
    expect(screen.getByText("engineering")).toBeTruthy();
  });

  it("slides back to the channel list", async () => {
    const user = userEvent.setup();
    renderRow(ENG.id);

    await user.click(screen.getByRole("button", { name: "Back to spaces" }));

    expect(useChannelPaneStore.getState().pane).toBe("list");
    expect(useChannelPaneStore.getState().animateTransition).toBe(true);
  });

  // #me can't be starred, so its well is empty — but the well is still there,
  // so the row doesn't change height (and everything below it shift) when you
  // switch spaces.
  it("offers a star on shared channels only", () => {
    renderRow(ENG.id);
    expect(screen.getByRole("button", { name: "Star space" })).toBeTruthy();

    renderRow(ME.id);
    expect(screen.getAllByRole("button", { name: "Star space" })).toHaveLength(
      1,
    );
  });

  // A channel the project doesn't have must not read as one that's still
  // loading, or the sidebar looks stuck rather than wrong.
  it("says so when the channel can't be resolved", () => {
    mocks.channels = [];
    renderRow("gone");
    expect(screen.getByText("Unavailable")).toBeTruthy();
  });
});
