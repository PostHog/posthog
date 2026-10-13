import type { LoopSchemas } from "@posthog/api-client/loops";
import { render, screen } from "@testing-library/react";
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
    useLoops: vi.fn(() => ({
      data: [] as LoopSchemas.Loop[],
      isLoading: false,
      isError: false,
    })),
  };
});

vi.mock("@posthog/ui/features/canvas/hooks/useWorkLayout", () => ({
  useWorkLayout: () => false,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: mocks.channels,
    isLoading: mocks.channelsLoading,
  }),
}));
vi.mock("@posthog/ui/features/feature-flags/useLoopsHogFlowsEnabled", () => ({
  useLoopsHogFlowsEnabled: () => false,
}));
vi.mock("@posthog/ui/features/canvas/components/ChannelHeader", () => ({
  ChannelHeader: () => <div>Personal space header</div>,
}));
vi.mock("@posthog/ui/hooks/useSetHeaderContent", () => ({
  useSetHeaderContent: () => {},
}));
vi.mock("@posthog/ui/features/loops/loopWizardDialogStore", () => ({
  openNewLoop: vi.fn(),
}));
vi.mock("@posthog/ui/features/loops/hooks/useLoops", () => ({
  useLoops: mocks.useLoops,
  useLoopLimits: () => null,
  useLoopLimitReason: () => null,
}));
vi.mock("@posthog/ui/features/loops/components/LoopBuilderComposer", () => ({
  LoopBuilderComposer: () => null,
}));
vi.mock("@posthog/ui/features/loops/components/LoopFallbacks", () => ({
  LoopsEmptyNotice: () => null,
  LoopsSkeleton: () => <div>Loading loops</div>,
}));
vi.mock("@posthog/ui/features/loops/components/LoopsTable", () => ({
  LoopsTable: ({ loops }: { loops: { id: string; name: string }[] }) => (
    <div>
      {loops.map((loop) => (
        <div key={loop.id}>{loop.name}</div>
      ))}
    </div>
  ),
}));
vi.mock("@posthog/ui/features/loops/components/LoopsEmptyState", () => ({
  LoopsEmptyState: () => null,
}));
vi.mock("@posthog/ui/features/loops/components/LoopTemplatesSection", () => ({
  LoopTemplatesSection: () => null,
}));

import { WebsiteChannelLoops } from "./WebsiteChannelLoops";

function loop(
  id: string,
  name: string,
  folderId: string | null,
): LoopSchemas.Loop {
  return {
    id,
    name,
    description: "",
    visibility: "team",
    enabled: true,
    disabled_reason: null,
    context_target: folderId ? { channel_id: folderId, name: folderId } : null,
  } as LoopSchemas.Loop;
}

describe("WebsiteChannelLoops", () => {
  beforeEach(() => {
    mocks.channels = [mocks.personalSpace];
    mocks.channelsLoading = false;
    mocks.useLoops.mockReset();
    mocks.useLoops.mockReturnValue({
      data: [],
      isLoading: false,
      isError: false,
    });
  });

  it("shows only loops attached to the personal space", () => {
    mocks.useLoops.mockReturnValue({
      data: [
        loop("a", "Mine", "personal-space"),
        loop("b", "Unattached", null),
        loop("c", "Elsewhere", "other"),
      ],
      isLoading: false,
      isError: false,
    });

    render(<WebsiteChannelLoops channelId="personal-space" />);

    expect(screen.getByText("Mine")).toBeInTheDocument();
    expect(screen.queryByText("Unattached")).not.toBeInTheDocument();
    expect(screen.queryByText("Elsewhere")).not.toBeInTheDocument();
  });

  it("waits for the Personal space to resolve before choosing a list", () => {
    mocks.channels = [];
    mocks.channelsLoading = true;

    render(<WebsiteChannelLoops channelId="personal-space" />);

    expect(screen.getByText("Loading loops")).toBeInTheDocument();
    expect(mocks.useLoops).not.toHaveBeenCalled();
  });
});
