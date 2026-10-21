import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createChannel: vi.fn(),
  setup: vi.fn(),
  generate: vi.fn(),
  setupFlag: vi.fn(),
  navigate: vi.fn(),
  track: vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: mocks.track }));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => mocks.navigate,
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({ setupTaskChannel: mocks.setup }),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: null }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({ members: [] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => mocks.setupFlag(),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannelMutations: () => ({
    createChannel: mocks.createChannel,
    isCreating: false,
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useGenerateContext", () => ({
  useGenerateContext: () => ({ generate: mocks.generate, isStarting: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  useUpdateTaskChannelRepositories: () => ({
    mutateAsync: vi.fn(),
    isPending: false,
  }),
}));
vi.mock(
  "@posthog/ui/features/integrations/components/RepositoriesField",
  () => ({
    RepositoriesField: () => <div data-testid="repositories-field" />,
  }),
);
vi.mock("@posthog/ui/features/canvas/components/MemberSearch", () => ({
  MemberSearch: () => null,
}));
vi.mock("@posthog/ui/features/canvas/components/MemberList", () => ({
  MemberList: () => null,
}));

import { CreateChannelModal } from "./CreateChannelModal";

// The step transition keeps the leaving step mounted while it animates out, so
// the newest button of a name is the one on the current step.
const current = (label: string) => {
  const matches = screen.getAllByText(label);
  return matches[matches.length - 1] as HTMLElement;
};

describe("CreateChannelModal setup steps", () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.setupFlag.mockReturnValue(true);
    window.scrollTo = () => {};
  });

  it("keeps a failed setup and retries it without creating another space", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();
    mocks.createChannel.mockResolvedValue({ id: "space-1" });
    mocks.setup.mockRejectedValueOnce(
      new Error("Setup is unavailable. Try again."),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CreateChannelModal open onOpenChange={onOpenChange} />
      </QueryClientProvider>,
    );

    await user.type(screen.getByLabelText("Name"), "search");
    await user.click(current("Next"));
    await user.click(screen.getByText("A feature"));
    await user.type(screen.getByLabelText("Feature"), "Search filters");
    await user.click(current("Next"));
    await user.click(current("Create"));

    expect(
      await screen.findByText("Setup is unavailable. Try again."),
    ).toBeTruthy();
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(mocks.navigate).not.toHaveBeenCalled();
    expect(mocks.track).not.toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ action_type: "setup_started" }),
    );
    const firstInput = mocks.setup.mock.calls[0];
    expect(firstInput).toEqual([
      "space-1",
      expect.objectContaining({
        kind: "feature",
        feature: expect.objectContaining({ name: "Search filters" }),
      }),
    ]);

    let finish: () => void = () => {};
    mocks.setup.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    await user.dblClick(screen.getByRole("button", { name: "Retry setup" }));
    expect(mocks.setup).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: /Retry setup/ })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(mocks.setup).toHaveBeenLastCalledWith(...firstInput);
    finish();
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.createChannel).toHaveBeenCalledOnce();
    expect(mocks.navigate).toHaveBeenCalledWith({
      to: "/spaces/$channelId",
      params: { channelId: "space-1" },
    });
    expect(mocks.track).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        action_type: "setup_started",
        channel_id: "space-1",
      }),
    );
  });
  it("walks from the name through the setup step to repositories and back", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CreateChannelModal open onOpenChange={vi.fn()} />
      </QueryClientProvider>,
    );

    await user.type(screen.getByLabelText("Name"), "growth");
    await user.click(current("Next"));
    expect(screen.getByText("What is this space for?")).toBeTruthy();

    expect(screen.getByLabelText("Describe it")).toBeTruthy();

    await user.click(screen.getByText("A goal"));
    expect(screen.getByLabelText("Goal")).toBeTruthy();
    await user.click(current("Next"));
    expect(screen.queryByText("Repositories")).toBeNull();

    await user.type(screen.getByLabelText("Goal"), "Grow weekly activation");
    await user.click(current("Next"));
    expect(screen.getByText("Repositories")).toBeTruthy();
    expect(screen.getByText(/A goal needs a repository/)).toBeTruthy();

    await user.click(current("Back"));
    expect(screen.getAllByText("What is this space for?").length).toBe(1);
    expect(screen.getByLabelText("Goal")).toHaveProperty(
      "value",
      "Grow weekly activation",
    );
  });

  it("creates a space through the describe step without setup when the flag is off", async () => {
    const user = userEvent.setup();
    mocks.setupFlag.mockReturnValue(false);
    mocks.createChannel.mockResolvedValue({ id: "space-1" });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CreateChannelModal open onOpenChange={vi.fn()} />
      </QueryClientProvider>,
    );

    await user.type(screen.getByLabelText("Name"), "growth");
    await user.click(current("Next"));
    expect(screen.queryByText("What is this space for?")).toBeNull();
    expect(screen.getByText("What's this space about?")).toBeTruthy();

    await user.type(
      document.getElementById("context-description") as HTMLElement,
      "Weekly activation work",
    );
    await user.click(current("Next"));
    await user.click(current("Create"));

    await waitFor(() =>
      expect(mocks.navigate).toHaveBeenCalledWith({
        to: "/spaces/$channelId",
        params: { channelId: "space-1" },
      }),
    );
    expect(mocks.generate).toHaveBeenCalledWith({
      channelId: "space-1",
      channelName: "growth",
      description: "Weekly activation work",
    });
    expect(mocks.setup).not.toHaveBeenCalled();
  });
});
