import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
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
  useFeatureFlag: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannelMutations: () => ({ createChannel: vi.fn(), isCreating: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useGenerateContext", () => ({
  useGenerateContext: () => ({ generate: vi.fn(), isStarting: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useSetupSpace", () => ({
  useSetupSpace: () => ({ setup: vi.fn(), isStarting: false }),
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
  it("walks from the name through the setup step to repositories and back", async () => {
    const user = userEvent.setup();
    render(<CreateChannelModal open onOpenChange={vi.fn()} />);

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
});
