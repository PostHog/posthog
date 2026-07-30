import { render, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  fetchNextPage: vi.fn(),
  hasNextPage: true,
  isFetchingNextPage: false,
}));

vi.mock("@posthog/quill", () => ({
  Button: ({ children }: { children: ReactNode }) => (
    <button type="button">{children}</button>
  ),
  Empty: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  EmptyDescription: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  EmptyHeader: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  EmptyMedia: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  EmptyTitle: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  PopoverContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  Spinner: () => <div>Loading</div>,
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: null }),
}));
vi.mock("@posthog/ui/features/canvas/components/ActivityView", () => ({
  ActivityRow: () => <div>Activity row</div>,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [] }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useMarkTaskActivityRead", () => ({
  useMarkTaskActivityRead: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskActivity", () => ({
  useTaskActivity: () => ({
    items: [],
    unreadCount: 0,
    isLoading: false,
    hasNextPage: mocks.hasNextPage,
    isFetchingNextPage: mocks.isFetchingNextPage,
    fetchNextPage: mocks.fetchNextPage,
  }),
}));
vi.mock("@posthog/ui/primitives/hooks/useInView", () => ({
  useInView: () => [vi.fn(), true],
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { ActivityHoverCard } from "./ActivityHoverCard";

describe("ActivityHoverCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.hasNextPage = true;
    mocks.isFetchingNextPage = false;
  });

  it("loads the next page when the bottom sentinel is visible", async () => {
    render(<ActivityHoverCard onClose={vi.fn()} />);

    await waitFor(() => expect(mocks.fetchNextPage).toHaveBeenCalledOnce());
  });

  it("does not load when there is no next page", async () => {
    mocks.hasNextPage = false;
    render(<ActivityHoverCard onClose={vi.fn()} />);

    await waitFor(() => expect(mocks.fetchNextPage).not.toHaveBeenCalled());
  });
});
