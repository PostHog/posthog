import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  channels: [] as { id: string; name: string; path: string }[],
  starredRefToShortcutId: new Map<string, string>(),
  star: vi.fn(() => Promise.resolve()),
  unstar: vi.fn(() => Promise.resolve()),
  navigate: vi.fn(),
  setCurrentChannel: vi.fn(),
  track: vi.fn(),
  pathname: "/code",
}));

vi.mock("@posthog/ui/shell/analytics", () => ({
  track: (...args: unknown[]) => mocks.track(...args),
}));
vi.mock("@tanstack/react-router", () => ({
  useNavigate: () => mocks.navigate,
  useRouterState: ({
    select,
  }: {
    select: (s: { location: { pathname: string } }) => string;
  }) => select({ location: { pathname: mocks.pathname } }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: mocks.channels, isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelStars", () => ({
  useChannelStars: () => ({
    starredRefToShortcutId: mocks.starredRefToShortcutId,
  }),
  useChannelStarMutations: () => ({ star: mocks.star, unstar: mocks.unstar }),
}));
vi.mock("@posthog/ui/features/canvas/stores/currentChannelStore", () => ({
  useCurrentChannelStore: (
    selector: (s: { setCurrentChannel: (id: string) => void }) => unknown,
  ) => selector({ setCurrentChannel: mocks.setCurrentChannel }),
}));
vi.mock("@posthog/ui/features/canvas/components/CreateChannelModal", () => ({
  CreateChannelModal: ({ open }: { open: boolean }) =>
    open ? <div data-testid="create-space-modal" /> : null,
}));

import { useSpacesSidebarStore } from "@posthog/ui/features/canvas/stores/spacesSidebarStore";
import { AllSpacesSection } from "./AllSpacesSection";

const ME = { id: "me-id", name: "me", path: "/me" };
const ENG = { id: "eng-id", name: "eng", path: "/eng" };
const ADS = { id: "ads-id", name: "ads", path: "/ads" };

function renderSection() {
  return render(
    <Theme>
      <AllSpacesSection />
    </Theme>,
  );
}

describe("AllSpacesSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.channels = [ME, ENG, ADS];
    mocks.starredRefToShortcutId = new Map();
    mocks.pathname = "/code";
    useSpacesSidebarStore.setState({ openAddSpace: true });
  });

  it("lists shared spaces alphabetically and leaves the personal space out", () => {
    renderSection();
    const rows = screen
      .getAllByRole("button")
      .map((b) => b.textContent)
      .filter((t) => t === "ads" || t === "eng" || t === "me");
    expect(rows).toEqual(["ads", "eng"]);
  });

  it("opens the space on row click rather than pinning it", () => {
    renderSection();
    fireEvent.click(screen.getByText("eng"));
    expect(mocks.navigate).toHaveBeenCalledWith({
      to: "/website/$channelId",
      params: { channelId: ENG.id },
    });
    expect(mocks.setCurrentChannel).toHaveBeenCalledWith(ENG.id);
    expect(mocks.star).not.toHaveBeenCalled();
  });

  it("pins on the star without opening the space", () => {
    renderSection();
    fireEvent.click(screen.getAllByLabelText("Pin space")[0]);
    expect(mocks.star).toHaveBeenCalledWith(ADS);
    expect(mocks.navigate).not.toHaveBeenCalled();
  });

  it("unpins an already-pinned space through its shortcut", () => {
    mocks.starredRefToShortcutId = new Map([[ENG.path, "shortcut-1"]]);
    renderSection();
    fireEvent.click(screen.getByLabelText("Unpin space"));
    expect(mocks.unstar).toHaveBeenCalledWith("shortcut-1");
  });

  it("collapses to just the section label", () => {
    useSpacesSidebarStore.setState({ openAddSpace: false });
    renderSection();
    expect(screen.getByText("All spaces")).toBeTruthy();
    expect(screen.queryByText("eng")).toBeNull();
  });

  it("opens the create-space modal from the New space row", () => {
    renderSection();
    fireEvent.click(screen.getByText("New space"));
    expect(screen.getByTestId("create-space-modal")).toBeTruthy();
  });
});
