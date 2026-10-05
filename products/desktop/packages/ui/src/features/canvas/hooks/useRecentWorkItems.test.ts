import type { ChannelSessionFacts } from "@posthog/core/canvas/channelItems";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { selectRecentWorkItems } from "./useRecentWorkItems";

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
  ])("$case", ({ over, expected }) => {
    expect(keys(over)).toEqual(expected);
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
