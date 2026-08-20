import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  currentProject: undefined as { id: number; name: string } | undefined,
  channels: [] as { id: string; name: string }[],
  location: undefined as Record<string, unknown> | null | undefined,
  orgProjectsMap: {} as Record<string, unknown>,
  selectProject: vi.fn(),
  navigate: vi.fn(),
}));

vi.mock("@posthog/ui/features/projects/useProjects", () => ({
  useProjects: () => ({ currentProject: state.currentProject }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: state.channels, isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useDashboards", () => ({
  useCanvasLocation: () => ({ location: state.location, isFetching: false }),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (select: (s: unknown) => unknown) =>
    select({ orgProjectsMap: state.orgProjectsMap }),
}));
vi.mock("@posthog/ui/features/auth/useAuthMutations", () => ({
  useSelectProjectMutation: () => ({
    mutateAsync: state.selectProject,
    isPending: false,
  }),
}));
vi.mock("@posthog/ui/router/navigationBridge", () => ({
  // Delegates rather than passing the mock directly: this factory runs once, so a spy captured
  // here would not be the one beforeEach installs.
  navigateToChannelDashboard: (...args: unknown[]) => state.navigate(...args),
}));
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, to }: { children?: React.ReactNode; to: string }) => (
    <a href={to}>{children}</a>
  ),
}));

import { CanvasNotFound } from "@posthog/ui/features/canvas/components/CanvasNotFound";

const ELSEWHERE = {
  canvasId: "dash-1",
  canvasName: "Revenue",
  channelId: "chan-9",
  projectId: 42,
  projectName: "Marketing",
  organizationId: "org-1",
  organizationName: "Acme",
  url: "https://us.posthog.com/code/canvas/chan-9/dash-1",
};

describe("CanvasNotFound", () => {
  beforeEach(() => {
    state.currentProject = { id: 2, name: "Website" };
    state.channels = [];
    state.location = null;
    state.orgProjectsMap = {};
    state.selectProject = vi.fn().mockResolvedValue(undefined);
    state.navigate = vi.fn();
  });

  // Naming the project is the whole point of the screen: without it the message is
  // indistinguishable from the empty-canvas state it replaced.
  it("names the project it looked in when the canvas cannot be located", () => {
    render(<CanvasNotFound channelId="chan-1" dashboardId="dash-1" />);

    expect(screen.getByText(/not in Website/)).toBeInTheDocument();
    expect(screen.getByText(/Switch to the project/)).toBeInTheDocument();
  });

  // The channel lives in the canvas's project too, so a link from elsewhere names one that
  // isn't here either and "back to it" would be a second dead end.
  it.each([
    [
      "offers the channel when it is in this project",
      [{ id: "chan-1", name: "Growth" }],
      "Back to Growth",
    ],
    ["falls back to spaces when it is not", [], "Go to spaces"],
  ])("%s", (_label, channels, expectedLabel) => {
    state.channels = channels;

    render(<CanvasNotFound channelId="chan-1" dashboardId="dash-1" />);

    expect(screen.getByText(expectedLabel)).toBeInTheDocument();
  });

  it("offers a switch when the owning project is one the session holds", async () => {
    state.location = ELSEWHERE;
    state.orgProjectsMap = {
      "org-1": { orgName: "Acme", projects: [{ id: 42, name: "Marketing" }] },
    };

    render(<CanvasNotFound channelId="chan-1" dashboardId="dash-1" />);
    fireEvent.click(
      screen.getByRole("button", { name: /Switch to Marketing/ }),
    );

    await waitFor(() => expect(state.navigate).toHaveBeenCalled());
    expect(state.selectProject).toHaveBeenCalledWith(42);
    // The channel comes from the location, not the route that just 404ed.
    expect(state.navigate).toHaveBeenCalledWith("chan-9", "dash-1");
    // Selecting a project navigates away on its own, so opening the canvas has to land after
    // it. This ordering is invisible in the source and easy to undo.
    expect(state.selectProject.mock.invocationCallOrder[0]).toBeLessThan(
      state.navigate.mock.invocationCallOrder[0],
    );
  });

  // A session granted a single project cannot switch into another, so it must not be shown a
  // button that would fail.
  it("tells a single-project session to sign in again instead", () => {
    state.location = ELSEWHERE;
    state.orgProjectsMap = {
      "org-2": { orgName: "Other", projects: [{ id: 2, name: "Website" }] },
    };

    render(<CanvasNotFound channelId="chan-1" dashboardId="dash-1" />);

    expect(screen.queryByText("Switch to Marketing")).not.toBeInTheDocument();
    expect(
      screen.getByText(/Sign in again and pick that project/),
    ).toBeInTheDocument();
  });
});
