import type { Task, UserBasic } from "@posthog/shared/domain-types";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  pages: [] as { tasks: Task[]; count: number }[],
  archivedTaskIds: new Set<string>(),
  blockedTaskIds: new Set<string>(),
  pinnedTaskIds: new Set<string>(),
  viewedAt: {} as Record<
    string,
    { lastViewedAt: number | null; lastActivityAt: number | null }
  >,
}));

vi.mock("@posthog/ui/features/archive/useArchivedTaskIds", () => ({
  useArchivedTaskIds: () => mocks.archivedTaskIds,
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({}),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useBlockedSessionCount", () => ({
  useBlockedTaskIds: () => mocks.blockedTaskIds,
}));
vi.mock("@posthog/ui/features/sidebar/usePinnedTasks", () => ({
  usePinnedTasks: () => ({ pinnedTaskIds: mocks.pinnedTaskIds }),
}));
vi.mock("@posthog/ui/features/sidebar/useTaskViewed", () => ({
  useTaskViewed: () => ({ timestamps: mocks.viewedAt }),
}));
vi.mock("@tanstack/react-query", () => ({
  useQueries: () => mocks.pages,
  useQuery: vi.fn(),
  useQueryClient: vi.fn(),
}));

import { spacePeople, useRecentSpaceTasks } from "./useRecentSpaceTasks";

function user(name: string): UserBasic {
  return {
    id: name.length,
    uuid: `uuid-${name}`,
    first_name: name,
    last_name: "Tester",
    email: `${name}@example.com`,
  };
}

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Task",
    description: "",
    created_at: new Date(500).toISOString(),
    updated_at: new Date(1_000).toISOString(),
    last_activity_at: new Date(3_000).toISOString(),
    origin_product: "user_created",
    ...overrides,
  };
}

const ADA = user("ada");
const GRACE = user("grace");
const ALAN = user("alan");

describe("useRecentSpaceTasks", () => {
  beforeEach(() => {
    mocks.pages = [];
    mocks.archivedTaskIds = new Set();
    mocks.blockedTaskIds = new Set();
    mocks.pinnedTaskIds = new Set();
    mocks.viewedAt = {};
  });

  it("builds expanded-space rows from live blocked and viewed facts", () => {
    mocks.pages = [{ tasks: [task()], count: 1 }];
    mocks.blockedTaskIds = new Set(["task-1"]);
    mocks.viewedAt = {
      "task-1": { lastViewedAt: 2_000, lastActivityAt: null },
    };
    const spaceIds = ["space-1"];

    const { result, rerender } = renderHook(() =>
      useRecentSpaceTasks(spaceIds),
    );

    expect(result.current.get("space-1")?.items[0]).toMatchObject({
      id: "task-1",
      needsInput: true,
      unread: true,
    });

    mocks.viewedAt = {
      "task-1": { lastViewedAt: 4_000, lastActivityAt: null },
    };
    rerender();

    expect(result.current.get("space-1")?.items[0]?.unread).toBe(false);
  });

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
});
