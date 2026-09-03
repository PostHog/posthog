import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  // Inside the hoisted block, because `vi.hoisted` runs before module scope and
  // cannot reach a const declared out here.
  const personalSpace = {
    id: "personal-space",
    name: "personal",
    channelType: "personal",
    path: "/me",
  };
  return {
    personalSpace,
    channels: [personalSpace],
    channelsLoading: false,
    useLoops: vi.fn(() => ({ data: [], isLoading: false, isError: false })),
  };
});

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: mocks.channels,
    isLoading: mocks.channelsLoading,
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelHeader", () => ({
  ChannelHeader: () => <div>Personal space header</div>,
}));
vi.mock("@posthog/ui/hooks/useSetHeaderContent", () => ({
  useSetHeaderContent: () => {},
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  navigateToNewLoop: vi.fn(),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({
    members: [],
    isLoading: false,
    isError: false,
    isComplete: true,
  }),
}));
vi.mock("@posthog/ui/features/loops/hooks/useLoops", () => ({
  useLoops: mocks.useLoops,
  useLoopLimits: () => null,
}));
vi.mock("@posthog/ui/features/loops/components/LoopBuilderComposer", () => ({
  LoopBuilderComposer: () => null,
}));
vi.mock("@posthog/ui/features/loops/components/LoopFallbacks", () => ({
  LoopsEmptyNotice: () => null,
  LoopsSkeleton: () => <div>Loading loops</div>,
}));
vi.mock("@posthog/ui/features/loops/components/LoopRow", () => ({
  LoopRow: () => null,
}));
vi.mock("@posthog/ui/features/loops/components/LoopsEmptyState", () => ({
  LoopsEmptyState: () => null,
}));
vi.mock("@posthog/ui/features/loops/components/LoopTemplatesSection", () => ({
  LoopTemplatesSection: () => null,
}));
vi.mock("@posthog/ui/features/loops/components/LoopsListView", () => ({
  LoopsListView: ({ headerContent }: { headerContent?: ReactNode }) => (
    <div>
      {headerContent}
      Project loops registry
    </div>
  ),
}));

import { WebsiteChannelLoops } from "./WebsiteChannelLoops";

describe("WebsiteChannelLoops", () => {
  beforeEach(() => {
    mocks.channels = [mocks.personalSpace];
    mocks.channelsLoading = false;
    mocks.useLoops.mockClear();
  });

  it("shows the project loops registry in the personal space", () => {
    render(<WebsiteChannelLoops channelId="personal-space" />);

    expect(screen.getByText("Project loops registry")).toBeInTheDocument();
    expect(screen.getByText("Personal space header")).toBeInTheDocument();
  });

  it("waits for the Personal space to resolve before choosing a list", () => {
    mocks.channels = [];
    mocks.channelsLoading = true;

    render(<WebsiteChannelLoops channelId="personal-space" />);

    expect(screen.getByText("Loading loops")).toBeInTheDocument();
    expect(
      screen.queryByText("Project loops registry"),
    ).not.toBeInTheDocument();
    expect(mocks.useLoops).not.toHaveBeenCalled();
  });
});
