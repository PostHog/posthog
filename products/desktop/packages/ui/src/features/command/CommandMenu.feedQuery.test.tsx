import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

let taskResultsComplete = true;

// The palette pulls half the app in; everything irrelevant to the feed-query
// mode is stubbed to its empty state.
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: "user-1" } }),
}));
vi.mock("@posthog/di/container", () => ({ resolveService: () => ({}) }));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));
vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: () => ({ data: [] }),
}));
vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => new Set(),
}));
vi.mock("@posthog/ui/features/archive/useTaskArchive", () => ({
  useTaskArchive: () => ({
    requestArchive: vi.fn(),
    isArchiving: false,
    dialog: null,
  }),
}));
vi.mock("@posthog/ui/features/workspace/useWorkspace", () => ({
  useWorkspaces: () => ({ data: [], isFetched: true }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [], isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({
    members: [
      {
        id: 1,
        uuid: "uuid-shy",
        email: "shy@example.com",
        first_name: "Shy",
        last_name: "Alter",
      },
    ],
    isLoading: false,
    isError: false,
    isComplete: true,
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => true,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannelMap", () => ({
  useTaskChannelMap: () => new Map(),
}));
vi.mock("@posthog/ui/features/command/useFileSearchContext", () => ({
  useFileSearchContext: () => ({ repoPath: null }),
}));
vi.mock("@posthog/ui/features/command/useTaskSearch", () => ({
  useTaskSearch: () => ({ data: [] }),
}));
vi.mock("@posthog/ui/features/folders/useFolders", () => ({
  useFolders: () => ({ folders: [] }),
}));
vi.mock("@posthog/ui/router/useAppView", () => ({
  useAppView: () => ({ type: "home" }),
}));
vi.mock("@posthog/ui/features/sidebar/useTaskPrStatus", () => ({
  useTaskPrStatus: () => ({ prState: null, hasDiff: false, prUrl: null }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskFeedResults", () => ({
  useTaskFeedResults: (query: string | undefined) => ({
    tasks: query
      ? [
          {
            id: "task-1",
            title: "Fix billing address validation",
            repository: "example-org/webapp",
            channel: null,
          },
        ]
      : [],
    isComplete: taskResultsComplete,
    isLoading: false,
    issues: [],
  }),
  useFeedQueryPlan: () => ({ plan: undefined, isLoading: false }),
}));

const mocks = vi.hoisted(() => ({ navigateToFeed: vi.fn() }));
vi.mock("@posthog/ui/router/navigationBridge", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  navigateToFeed: mocks.navigateToFeed,
}));

import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import { useTaskFeedsStore } from "@posthog/ui/features/canvas/stores/taskFeedsStore";
import { CommandMenu } from "./CommandMenu";

describe("CommandMenu feed queries", () => {
  afterEach(() => {
    taskResultsComplete = true;
  });

  it("offers Save as feed and the matching tasks for a token query", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <CommandMenu open onOpenChange={() => {}} />
      </Theme>,
    );

    await user.type(
      screen.getByPlaceholderText(/Search commands and tasks/),
      "created-by:@me ",
    );
    // The footer advertises the save shortcut; the results are debounced.
    expect(await screen.findByText(/save search/)).toBeTruthy();
    expect(
      await screen.findByText(
        "Fix billing address validation",
        {},
        { timeout: 2000 },
      ),
    ).toBeTruthy();

    // ⌘S hands the query to the save modal.
    await user.keyboard("{Meta>}s{/Meta}");
    expect(
      await screen.findByText("Save search", { selector: "h2" }),
    ).toBeTruthy();
  });

  it("shows a selected command in the recent section", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <CommandMenu open onOpenChange={() => {}} />
      </Theme>,
    );

    await user.click(await screen.findByText("Toggle left sidebar"));

    expect(await screen.findByText("Recent")).toBeTruthy();
  });

  it("labels incomplete task search results", async () => {
    taskResultsComplete = false;
    const user = userEvent.setup();
    render(
      <Theme>
        <CommandMenu open onOpenChange={() => {}} />
      </Theme>,
    );

    await user.type(
      screen.getByPlaceholderText(/Search commands and tasks/),
      "created-by:@me ",
    );

    expect(
      await screen.findByText("Some matching tasks may not be shown."),
    ).toBeTruthy();
  });

  it("opens a saved search from the saved: filter", async () => {
    useAuthStore.setState({
      authState: { ...ANONYMOUS_AUTH_STATE, currentProjectId: 1 },
    });
    useTaskFeedsStore.setState({
      feeds: [
        {
          id: "feed-1",
          projectId: 1,
          ownerId: "user-1",
          name: "My failing tasks",
          query: "created-by:@me status:failed",
          createdAt: "2026-08-01T00:00:00Z",
        },
        {
          id: "feed-2",
          projectId: 2,
          ownerId: "user-1",
          name: "My failing tasks elsewhere",
          query: "created-by:@me status:failed",
          createdAt: "2026-08-01T00:00:00Z",
        },
      ],
    });
    const user = userEvent.setup();
    render(
      <Theme>
        <CommandMenu open onOpenChange={() => {}} />
      </Theme>,
    );

    await user.type(
      screen.getByPlaceholderText(/Search commands and tasks/),
      "saved:fail",
    );
    expect(screen.queryByText("My failing tasks elsewhere")).toBeNull();
    // A pure `saved:` query is saved-search completion, so it must not run a
    // task query or show unrelated task results or a match summary.
    expect(screen.queryByText("Fix billing address validation")).toBeNull();
    expect(screen.queryByText(/save search/)).toBeNull();
    await user.click(await screen.findByText("My failing tasks"));
    expect(mocks.navigateToFeed).toHaveBeenCalledWith("feed-1");
  });

  it("completes a key then a value from the always-on suggestions", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <CommandMenu open onOpenChange={() => {}} />
      </Theme>,
    );
    const input = screen.getByPlaceholderText<HTMLInputElement>(
      /Search commands and tasks/,
    );

    await user.type(input, "cre");
    await user.click(await screen.findByText("created-by:"));
    expect(input.value).toBe("created-by:");

    await user.click(await screen.findByText("@me"));
    expect(input.value).toBe("created-by:@me ");
  });

  it("keeps the command catalog out of a value completion", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <CommandMenu open onOpenChange={() => {}} />
      </Theme>,
    );
    const input = screen.getByPlaceholderText<HTMLInputElement>(
      /Search commands and tasks/,
    );

    expect(await screen.findByText("Actions")).toBeTruthy();
    await user.type(input, "created-by:");
    expect(await screen.findByText("Teammates")).toBeTruthy();
    expect(screen.queryByText("Actions")).toBeNull();
    expect(screen.queryByText("Navigation")).toBeNull();
  });

  it("scopes sections with type:", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <CommandMenu open onOpenChange={() => {}} />
      </Theme>,
    );
    const input = screen.getByPlaceholderText<HTMLInputElement>(
      /Search commands and tasks/,
    );

    // Commands render by default…
    expect(await screen.findByText("Actions")).toBeTruthy();
    // …and a task scope drops them while keeping the task query running.
    await user.type(input, "type:task billing ");
    expect(screen.queryByText("Actions")).toBeNull();
    expect(
      await screen.findByText(
        "Fix billing address validation",
        {},
        { timeout: 2000 },
      ),
    ).toBeTruthy();
  });
});
