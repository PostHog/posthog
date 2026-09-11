import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  currentProject: undefined as { id: number; name: string } | undefined,
  channels: [] as { id: string; name: string }[],
  channelsLoading: false,
  channelsError: null as Error | null,
}));

vi.mock("@posthog/ui/features/projects/useProjects", () => ({
  useProjects: () => ({ currentProject: state.currentProject }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({
    channels: state.channels,
    isLoading: state.channelsLoading,
    isError: state.channelsError !== null,
    isFetching: false,
    error: state.channelsError,
    refetch: () => {},
  }),
}));
vi.mock("@posthog/ui/router/routeSkeletons", () => ({
  CanvasSkeleton: () => <div data-testid="canvas-skeleton" />,
}));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children?: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

import { CanvasNotFound } from "@posthog/ui/features/canvas/components/CanvasNotFound";

describe("CanvasNotFound", () => {
  it.each([
    [
      "the channel is visible, so the canvas was deleted",
      [{ id: "chan-1", name: "Growth" }],
      [/may have been deleted/, "Back to Growth"],
    ],
    [
      "the channel is not visible, so access or project is the reason",
      [],
      [/don't have access/, /isn't in Marketing/, "Go to spaces"],
    ],
  ])("says why when %s", (_label, channels, expectedTexts) => {
    state.currentProject = { id: 2, name: "Marketing" };
    state.channels = channels;
    state.channelsLoading = false;
    state.channelsError = null;

    render(<CanvasNotFound channelId="chan-1" />);

    for (const text of expectedTexts) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
  });

  it("waits for the channel list before choosing a reason", () => {
    state.currentProject = { id: 2, name: "Marketing" };
    state.channels = [];
    state.channelsLoading = true;
    state.channelsError = null;

    render(<CanvasNotFound channelId="chan-1" />);

    expect(screen.getByTestId("canvas-skeleton")).toBeInTheDocument();
    expect(screen.queryByText(/canvas/i)).not.toBeInTheDocument();
  });

  it("offers a retry when the channel list is the thing that failed", () => {
    state.currentProject = { id: 2, name: "Marketing" };
    state.channels = [];
    state.channelsLoading = false;
    state.channelsError = new Error("Failed to fetch");

    render(<CanvasNotFound channelId="chan-1" />);

    expect(screen.getByText(/Failed to fetch/)).toBeInTheDocument();
    expect(screen.getByText("Try again")).toBeInTheDocument();
    expect(screen.queryByText(/don't have access/)).not.toBeInTheDocument();
  });
});
