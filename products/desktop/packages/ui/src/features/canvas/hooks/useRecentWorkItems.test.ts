import type { ChannelSessionFacts } from "@posthog/core/canvas/channelItems";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  RECENT_WORK_CAP,
  recentWorkPageSize,
  selectRecentWorkItems,
} from "./useRecentWorkItems";

const ME = "me-uuid";
const OLD = 1_000;
const NEW = 9_000;
const VIEWED_NOW = 100_000;

const NO_SESSION_FACTS: ChannelSessionFacts = {
  needsInputTaskIds: new Set(),
  viewedTimestamps: {},
  workspaceByTaskId: new Map(),
};

function canvas(over: Partial<DashboardRecord> = {}): DashboardRecord {
  return {
    id: "canvas-old",
    channelId: "c1",
    name: "Canvas",
    kind: "freeform" as const,
    description: "",
    templateId: "freeform",
    createdAt: 0,
    updatedAt: OLD,
    createdByUuid: ME,
    ...over,
  };
}

function task(over: Partial<Task> = {}): Task {
  return {
    id: "task-new",
    title: "Task",
    created_at: new Date(0).toISOString(),
    last_activity_at: new Date(NEW).toISOString(),
    ...over,
  } as Task;
}

function select(
  over: Partial<Parameters<typeof selectRecentWorkItems>[0]> = {},
) {
  return selectRecentWorkItems({
    dashboards: [],
    tasks: [],
    pinnedTasks: [],
    lastViewedByCanvasId: {},
    meUuid: ME,
    archivedTaskIds: new Set(),
    pinnedTaskIds: new Set(),
    sessionFacts: NO_SESSION_FACTS,
    ...over,
  });
}

function keys(over: Partial<Parameters<typeof selectRecentWorkItems>[0]> = {}) {
  return select(over).map(({ item }) => item.key);
}

describe("selectRecentWorkItems", () => {
  it.each([
    {
      case: "keeps a canvas the user just opened below newer work",
      over: {
        dashboards: [canvas()],
        tasks: [task()],
        lastViewedByCanvasId: { "canvas-old": VIEWED_NOW },
      },
      expected: ["task:task-new", "canvas:canvas-old"],
    },
    {
      case: "keeps a task the user just opened below newer work",
      over: {
        dashboards: [canvas({ id: "canvas-new", updatedAt: NEW })],
        tasks: [
          task({
            id: "task-old",
            last_activity_at: new Date(OLD).toISOString(),
          }),
        ],
        sessionFacts: {
          ...NO_SESSION_FACTS,
          viewedTimestamps: { "task-old": { lastViewedAt: VIEWED_NOW } },
        },
      },
      expected: ["canvas:canvas-new", "task:task-old"],
    },
    {
      case: "lists a canvas somebody else made once the user has opened it",
      over: {
        dashboards: [canvas({ createdByUuid: "other-uuid" })],
        lastViewedByCanvasId: { "canvas-old": VIEWED_NOW },
      },
      expected: ["canvas:canvas-old"],
    },
    {
      case: "drops a canvas somebody else made that the user never opened",
      over: { dashboards: [canvas({ createdByUuid: "other-uuid" })] },
      expected: [],
    },
    {
      case: "lists a pinned task the recent fetch did not return",
      over: {
        pinnedTasks: [task({ id: "task-pinned" })],
        pinnedTaskIds: new Set(["task-pinned"]),
      },
      expected: ["task:task-pinned"],
    },
    {
      case: "lists a pinned task once when both fetches return it",
      over: {
        tasks: [task()],
        pinnedTasks: [task()],
        pinnedTaskIds: new Set(["task-new"]),
      },
      expected: ["task:task-new"],
    },
  ])("$case", ({ over, expected }) => {
    expect(keys(over)).toEqual(expected);
  });

  it("caps only the unpinned work, so newer pins cannot empty Recent", () => {
    const pins = Array.from({ length: RECENT_WORK_CAP }, (_, index) =>
      task({
        id: `pin-${index}`,
        last_activity_at: new Date(NEW + index).toISOString(),
      }),
    );
    const recent = task({
      id: "recent",
      last_activity_at: new Date(OLD).toISOString(),
    });

    expect(
      keys({
        tasks: [recent],
        pinnedTasks: pins,
        pinnedTaskIds: new Set(pins.map((pin) => pin.id)),
      }),
    ).toContain("task:recent");
  });

  it("carries each item's own channel", () => {
    expect(
      select({
        dashboards: [canvas({ channelId: "canvas-channel" })],
        tasks: [task({ channel: "task-channel" })],
        lastViewedByCanvasId: { "canvas-old": VIEWED_NOW },
      }),
    ).toEqual([
      expect.objectContaining({ channelId: "task-channel" }),
      expect.objectContaining({ channelId: "canvas-channel" }),
    ]);
  });
});

describe("recentWorkPageSize", () => {
  it.each([
    { pins: 0, expected: RECENT_WORK_CAP },
    { pins: 7, expected: RECENT_WORK_CAP + 7 },
    { pins: 500, expected: 100 },
  ])(
    "asks for room past $pins pins, so pins cannot fill Recent's page",
    ({ pins, expected }) => {
      expect(recentWorkPageSize(pins)).toBe(expected);
    },
  );
});
