import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Hoisted so the module factory below can read them, and each test can steer
// the current route / assert navigations.
const router = vi.hoisted(() => ({
  pathname: "/spaces/team/artifacts",
  navigate: vi.fn(),
}));
const channels = vi.hoisted(() => ({
  current: [
    {
      id: "team",
      name: "Team",
      channelType: "public" as const,
      starred: false,
    },
  ],
  star: vi.fn().mockResolvedValue(undefined),
  unstar: vi.fn().mockResolvedValue(undefined),
  copyLink: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => router.navigate,
  useRouterState: <T,>({
    select,
  }: {
    select: (state: { location: { pathname: string } }) => T;
  }) => select({ location: { pathname: router.pathname } }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: channels.current, isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelStars", () => ({
  useChannelStarMutations: () => ({
    star: channels.star,
    unstar: channels.unstar,
  }),
}));
vi.mock("@posthog/ui/features/canvas/utils/copyChannelLink", () => ({
  copyChannelLink: channels.copyLink,
}));

import { ChannelBreadcrumb } from "./ChannelBreadcrumb";

describe("ChannelBreadcrumb", () => {
  beforeEach(() => {
    router.pathname = "/spaces/team/artifacts";
    router.navigate.mockClear();
    channels.star.mockClear();
    channels.unstar.mockClear();
    channels.copyLink.mockClear();
    channels.current[0].starred = false;
  });

  it("closes title editing when the editable leaf changes", () => {
    const onRename = vi.fn();
    const { rerender } = render(
      <Theme>
        <ChannelBreadcrumb
          channelName="Team"
          leafLabel="Task A"
          editScopeKey="task-a"
          onRename={onRename}
        />
      </Theme>,
    );

    // A renamable leaf stays a live control, so it isn't marked disabled.
    expect(screen.getByRole("button", { name: "Task A" })).not.toHaveAttribute(
      "aria-disabled",
    );

    // One click opens the editor — the leaf never navigates, so a click has
    // nothing else to mean.
    fireEvent.click(screen.getByRole("button", { name: "Task A" }));
    expect(screen.getByRole("textbox")).toHaveValue("Task A");

    rerender(
      <Theme>
        <ChannelBreadcrumb
          channelName="Team"
          leafLabel="Task B"
          editScopeKey="task-b"
          onRename={onRename}
        />
      </Theme>,
    );

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("Task B")).toBeInTheDocument();
    expect(onRename).not.toHaveBeenCalled();
  });

  it("navigates home from the root segment on a sub-page", () => {
    render(
      <Theme>
        <ChannelBreadcrumb
          channelName="Team"
          channelId="team"
          leafLabel="Artifacts"
        />
      </Theme>,
    );

    const root = screen.getByRole("button", { name: /Team/ });
    expect(root).not.toHaveAttribute("aria-disabled", "true");
    fireEvent.click(root);
    expect(router.navigate).toHaveBeenCalledWith({
      to: "/spaces/$channelId",
      params: { channelId: "team" },
    });
  });

  it("links the middle segment to its section", () => {
    const onMiddleClick = vi.fn();
    render(
      <Theme>
        <ChannelBreadcrumb
          channelName="Team"
          channelId="team"
          middle={{ label: "Loops", onClick: onMiddleClick }}
          leafLabel="CI failure summary"
        />
      </Theme>,
    );

    // Every segment is a Button so they share padding and height; the leaf is
    // the current page, so it's the disabled one.
    expect(screen.getAllByRole("button")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Loops" }));
    expect(onMiddleClick).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "CI failure summary" }),
    ).toHaveAttribute("aria-disabled", "true");
  });

  it("disables the root segment on the space's own index", () => {
    router.pathname = "/spaces/team";
    render(
      <Theme>
        <ChannelBreadcrumb
          channelName="Team"
          channelId="team"
          leafLabel="Feed"
        />
      </Theme>,
    );

    const root = screen.getByRole("button", { name: /Team/ });
    expect(root).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(root);
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it("opens channel actions from the root segment", async () => {
    render(
      <Theme>
        <ChannelBreadcrumb
          channelName="Team"
          channelId="team"
          leafLabel="Artifacts"
        />
      </Theme>,
    );

    fireEvent.contextMenu(screen.getByRole("button", { name: /Team/ }));

    expect(await screen.findByText("Star channel")).toBeInTheDocument();
    expect(screen.getByText("Copy link to channel")).toBeInTheDocument();
  });

  it("runs star and copy actions for the channel", async () => {
    render(
      <Theme>
        <ChannelBreadcrumb channelName="Team" channelId="team" />
      </Theme>,
    );

    const root = screen.getByRole("button", { name: /Team/ });
    fireEvent.contextMenu(root);
    fireEvent.click(await screen.findByText("Star channel"));
    expect(channels.star).toHaveBeenCalledWith("team");

    fireEvent.contextMenu(root);
    fireEvent.click(await screen.findByText("Copy link to channel"));
    expect(channels.copyLink).toHaveBeenCalledWith("team", "title_bar");
  });

  it("offers to unstar a starred channel", async () => {
    channels.current[0].starred = true;
    render(
      <Theme>
        <ChannelBreadcrumb channelName="Team" channelId="team" />
      </Theme>,
    );

    fireEvent.contextMenu(screen.getByRole("button", { name: /Team/ }));
    fireEvent.click(await screen.findByText("Unstar channel"));

    expect(channels.unstar).toHaveBeenCalledWith("team");
  });
});
