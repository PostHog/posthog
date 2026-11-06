import type { Task, UserBasic } from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getTasksPage: vi.fn(),
  timestamps: {} as Record<string, { lastViewedAt: number | null }>,
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({ getTasksPage: mocks.getTasksPage }),
}));
vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => EMPTY_IDS,
}));
vi.mock("@posthog/ui/features/sidebar/usePinnedTasks", () => ({
  usePinnedTasks: () => ({ pinnedTaskIds: EMPTY_IDS }),
}));
vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({ timestamps: mocks.timestamps }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useBlockedSessionCount", () => ({
  useBlockedTaskIds: () => EMPTY_IDS,
}));

const EMPTY_IDS: ReadonlySet<string> = new Set();

import {
  type SpaceTasks,
  spacePeople,
  useRecentSpaceTasks,
} from "./useRecentSpaceTasks";

function user(name: string): UserBasic {
  return {
    id: name.length,
    uuid: `uuid-${name}`,
    first_name: name,
    last_name: "Tester",
    email: `${name}@example.com`,
  };
}

const ADA = user("ada");
const GRACE = user("grace");
const ALAN = user("alan");

describe("spacePeople", () => {
  it.each([
    {
      case: "puts the creator first even when they ran nothing",
      createdBy: ADA,
      ran: [GRACE, ALAN],
      limit: 5,
      expected: [ADA, GRACE, ALAN],
    },
    {
      case: "counts the creator once when they also ran something",
      createdBy: ADA,
      ran: [GRACE, ADA, GRACE],
      limit: 5,
      expected: [ADA, GRACE],
    },
    {
      case: "keeps the creator when the cap cuts the rest",
      createdBy: ALAN,
      ran: [ADA, GRACE],
      limit: 2,
      expected: [ALAN, ADA],
    },
    {
      case: "leads with whoever ran when the space has no creator",
      createdBy: null,
      ran: [GRACE, ADA],
      limit: 5,
      expected: [GRACE, ADA],
    },
  ])("$case", ({ createdBy, ran, limit, expected }) => {
    const tasks = ran.map((created_by) => ({ created_by }));
    expect(spacePeople(tasks, createdBy, limit)).toEqual(expected);
  });
});

const OPENED_AT = Date.UTC(2026, 0, 2);

function spaceTask(id: string, activityAt: number): Task {
  return {
    id,
    title: id,
    created_at: new Date(Date.UTC(2026, 0, 1)).toISOString(),
    last_activity_at: new Date(activityAt).toISOString(),
  } as Task;
}

// Newest first, the order the server pages a space in.
const FRESH = spaceTask("fresh", Date.UTC(2026, 0, 3));
const UNREAD = spaceTask("unread", Date.UTC(2026, 0, 2) - 1);

let queryClient: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return createElement(QueryClientProvider, { client: queryClient }, children);
}

function rowsOf(view: { result: { current: Map<string, SpaceTasks> } }) {
  return view.result.current.get("space-1")?.items.map((item) => item.id);
}

/** The tree with one space open, once its first page has arrived. */
async function openSpace() {
  const view = renderHook(() => useRecentSpaceTasks(["space-1"]), { wrapper });
  await waitFor(() => expect(rowsOf(view)).toEqual(["unread", "fresh"]));
  return view;
}

describe("useRecentSpaceTasks", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    mocks.timestamps = {
      fresh: { lastViewedAt: Date.UTC(2026, 0, 4) },
      unread: { lastViewedAt: Date.UTC(2026, 0, 1) },
    };
    mocks.getTasksPage.mockResolvedValue({
      tasks: [FRESH, UNREAD],
      count: 2,
    });
  });

  it("keeps a row where it is when the reader opens it", async () => {
    const view = await openSpace();

    // Opening the unread session marks it viewed. Its dot clears, but the row
    // must not drop below the quiet one under the reader's pointer.
    mocks.timestamps = {
      ...mocks.timestamps,
      unread: { lastViewedAt: OPENED_AT },
    };
    view.rerender();

    expect(rowsOf(view)).toEqual(["unread", "fresh"]);
  });

  it.each([
    { name: "unchanged", freshTask: FRESH },
    { name: "updated", freshTask: spaceTask("fresh", Date.UTC(2026, 0, 5)) },
  ])(
    "takes the viewed state again after an $name page is fetched",
    async ({ freshTask }) => {
      const view = await openSpace();

      mocks.timestamps = {
        ...mocks.timestamps,
        unread: { lastViewedAt: OPENED_AT },
      };
      mocks.getTasksPage.mockResolvedValue({
        tasks: [freshTask, UNREAD],
        count: 2,
      });
      await queryClient.refetchQueries();

      await waitFor(() => expect(rowsOf(view)).toEqual(["fresh", "unread"]));
    },
  );
});
