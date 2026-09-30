import type { TaskSearchResult } from "@posthog/shared/domain-types";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/browser-tabs/useOpenBrowserTab", () => ({
  useOpenBrowserTab: () => vi.fn(),
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => null,
}));
vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  useCurrentUser: () => ({ data: { uuid: "user-1" } }),
}));
vi.mock("@posthog/di/container", () => ({
  resolveService: () => ({}),
  resolveServiceOptional: () => null,
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
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
  useWorkspaces: () => ({ data: [], isFetched: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: () => ({ channels: [], isLoading: false }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => false,
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskFeedResults", () => ({
  useTaskFeedResults: () => ({
    tasks: [],
    isComplete: true,
    isLoading: false,
    issues: [],
  }),
  useFeedQueryPlan: () => ({ plan: undefined, isLoading: false }),
}));
vi.mock("@posthog/ui/features/folders/useFolders", () => ({
  useFolders: () => ({ folders: [] }),
}));
vi.mock("@posthog/ui/router/useAppView", () => ({
  useAppView: () => ({ type: "home" }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: () => ({
    members: [],
    isLoading: false,
    isError: false,
    isComplete: true,
  }),
}));
vi.mock("@posthog/ui/features/sidebar/useTaskPrStatus", () => ({
  useTaskPrStatus: () => ({ prState: null, hasDiff: false, prUrl: null }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannelMap", () => ({
  useTaskChannelMap: () => new Map(),
}));
vi.mock("@posthog/ui/features/command/useFileSearchContext", () => ({
  useFileSearchContext: () => ({ repoPath: null }),
}));

vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: () => ({
    data: [{ id: "task-a", title: "Run analytics queries", channel: null }],
  }),
}));

const searchResults: TaskSearchResult[] = [
  {
    id: "doc-task",
    kind: "task",
    title: "Run analytics queries",
    subtitle: "",
    task_id: "task-a",
    task_run_id: null,
    channel_id: null,
    updated_at: "2026-09-01T10:00:00Z",
    metadata: {},
  },
  {
    id: "doc-file",
    kind: "artifact",
    title: "run-log.jsonl",
    subtitle: "Nightly import check",
    task_id: "task-b",
    task_run_id: null,
    channel_id: null,
    updated_at: "2026-09-01T09:00:00Z",
    metadata: {},
  },
];
vi.mock("@posthog/ui/features/command/useTaskSearch", () => ({
  useTaskSearch: (query: string) => ({
    data: query ? searchResults : [],
  }),
}));

import { CommandMenu } from "./CommandMenu";

describe("CommandMenu global search", () => {
  it("lists a matching task above the files, without repeating it below", async () => {
    const user = userEvent.setup();
    render(
      <Theme>
        <CommandMenu open onOpenChange={() => {}} />
      </Theme>,
    );

    await user.type(
      screen.getByPlaceholderText(/Search commands and tasks/),
      "run",
    );

    await screen.findByText("run-log.jsonl");
    const rows = Array.from(document.querySelectorAll("[role='option']")).map(
      (row) => row.textContent,
    );
    expect(rows[0]).toContain("Run analytics queries");
    expect(rows[1]).toContain("run-log.jsonl");
    expect(screen.queryByText("Tasks")).toBeNull();
  });
});
