import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigate = vi.fn();
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => navigate }));
vi.mock("@posthog/ui/features/canvas/components/FeedQueryHighlight", () => ({
  FeedQueryHighlight: ({ query }: { query: string }) => <span>{query}</span>,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useProjectTaskFeeds", () => ({
  useProjectTaskFeeds: () => useTaskFeedsStore.getState().feeds,
}));
vi.mock("@posthog/quill", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@posthog/quill")>();
  return {
    ...actual,
    DropdownMenu: ({ children }: { children: ReactNode }) => <>{children}</>,
    DropdownMenuContent: ({ children }: { children: ReactNode }) => (
      <div>{children}</div>
    ),
    DropdownMenuItem: ({
      children,
      onClick,
    }: {
      children: ReactNode;
      onClick?: () => void;
    }) => (
      <button type="button" onClick={onClick}>
        {children}
      </button>
    ),
    DropdownMenuTrigger: ({ render }: { render: ReactElement }) => render,
  };
});

import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import type { ReactElement, ReactNode } from "react";
import { SavedSearchSwitcher } from "./SavedSearchSwitcher";

describe("SavedSearchSwitcher", () => {
  beforeEach(() => {
    navigate.mockClear();
    useTaskFeedsStore.setState({
      feeds: [
        {
          id: "feed-1",
          projectId: 1,
          ownerId: "user-1",
          name: "Billing work",
          query: "billing",
          createdAt: "2026-08-01T00:00:00Z",
        },
        {
          id: "feed-2",
          projectId: 1,
          ownerId: "user-1",
          name: "Onboarding",
          query: "welcome",
          createdAt: "2026-08-01T00:00:00Z",
        },
      ],
    });
  });

  it("shows the current saved search name as the trigger", () => {
    render(
      <Theme>
        <SavedSearchSwitcher currentFeedId="feed-1" />
      </Theme>,
    );
    const trigger = screen.getByRole("button", { name: "Switch saved search" });
    expect(trigger).toHaveTextContent("Billing work");
  });

  it("switches to another saved search from the dropdown", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <SavedSearchSwitcher currentFeedId="feed-1" />
      </Theme>,
    );

    await user.click(screen.getByText("Onboarding"));

    expect(navigate).toHaveBeenCalledWith({
      to: "/feeds/$feedId",
      params: { feedId: "feed-2" },
    });
  });
});
