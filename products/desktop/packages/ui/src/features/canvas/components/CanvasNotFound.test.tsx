import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  currentProject: undefined as { id: number; name: string } | undefined,
  channels: [] as { id: string; name: string }[],
}));

vi.mock("@posthog/ui/features/projects/useProjects", () => ({
  useProjects: () => ({ currentProject: state.currentProject }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: state.channels, isLoading: false }),
}));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children?: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

import { CanvasNotFound } from "@posthog/ui/features/canvas/components/CanvasNotFound";

describe("CanvasNotFound", () => {
  it("names the project it looked in and how to reach the canvas", () => {
    state.currentProject = { id: 2, name: "Marketing" };
    state.channels = [];

    render(<CanvasNotFound channelId="chan-1" />);

    expect(screen.getByText(/in Marketing/)).toBeInTheDocument();
    expect(screen.getByText(/switch to that project/)).toBeInTheDocument();
  });

  it.each([
    [
      "offers the channel when it is in this project",
      [{ id: "chan-1", name: "Growth" }],
      "Back to Growth",
    ],
    ["falls back to spaces when it is not", [], "Go to spaces"],
  ])("%s", (_label, channels, expectedLabel) => {
    state.currentProject = { id: 2, name: "Marketing" };
    state.channels = channels;

    render(<CanvasNotFound channelId="chan-1" />);

    expect(screen.getByText(expectedLabel)).toBeInTheDocument();
  });
});
