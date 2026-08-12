import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Hoisted so the module factory below can read them, and each test can steer
// the current route / assert navigations.
const router = vi.hoisted(() => ({
  pathname: "/website/team/artifacts",
  navigate: vi.fn(),
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

import { ChannelBreadcrumb } from "./ChannelBreadcrumb";

describe("ChannelBreadcrumb", () => {
  beforeEach(() => {
    router.pathname = "/website/team/artifacts";
    router.navigate.mockClear();
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
      to: "/website/$channelId",
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
    router.pathname = "/website/team";
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
});
