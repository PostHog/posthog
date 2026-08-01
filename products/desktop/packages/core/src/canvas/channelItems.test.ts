import type { Task, UserBasic } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  buildChannelItems,
  type ChannelItemModel,
  filterChannelItems,
} from "./channelItems";
import type { DashboardSummary } from "./dashboardSchemas";

const ME: UserBasic = {
  id: 1,
  uuid: "me-uuid",
  distinct_id: "me",
  first_name: "Ada",
  last_name: "Lovelace",
  email: "ada@posthog.com",
};

const OTHER: UserBasic = {
  id: 2,
  uuid: "other-uuid",
  distinct_id: "other",
  first_name: "Grace",
  last_name: "Hopper",
  email: "grace@posthog.com",
};

function canvas(over: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    id: "d1",
    channelId: "c1",
    name: "Canvas",
    templateId: "freeform",
    createdAt: 0,
    updatedAt: 1_000,
    ...over,
  } as DashboardSummary;
}

function task(over: Partial<Task> = {}): Task {
  return {
    id: "t1",
    title: "Task",
    updated_at: new Date(2_000).toISOString(),
    created_by: ME,
    ...over,
  } as Task;
}

const NONE: ReadonlySet<string> = new Set();

function build(options: Partial<Parameters<typeof buildChannelItems>[0]> = {}) {
  return buildChannelItems({
    dashboards: [],
    feedTasks: [],
    archivedTaskIds: NONE,
    pinnedTaskIds: NONE,
    ownedBy: null,
    ...options,
  });
}

describe("buildChannelItems", () => {
  it("merges canvases and tasks newest-first", () => {
    const items = build({
      dashboards: [canvas({ id: "old", updatedAt: 1_000 })],
      feedTasks: [
        task({ id: "new", updated_at: new Date(5_000).toISOString() }),
      ],
    });
    expect(items.map((i) => i.key)).toEqual(["task:new", "canvas:old"]);
  });

  it("drops archived tasks but keeps canvases", () => {
    const items = build({
      dashboards: [canvas()],
      feedTasks: [task({ id: "gone" })],
      archivedTaskIds: new Set(["gone"]),
    });
    expect(items.map((i) => i.kind)).toEqual(["canvas"]);
  });

  it("marks pinned state from each source's own signal", () => {
    const items = build({
      dashboards: [canvas({ id: "pinned-canvas", pinnedAt: 42 })],
      feedTasks: [task({ id: "pinned-task" })],
      pinnedTaskIds: new Set(["pinned-task"]),
    });
    expect(items.every((i) => i.pinned)).toBe(true);
  });

  it("falls back to a placeholder title for untitled tasks", () => {
    const [item] = build({
      feedTasks: [task({ title: "" })],
    });
    expect(item.title).toBe("Untitled task");
  });

  it("treats an unparseable updated_at as epoch rather than NaN", () => {
    const [item] = build({
      feedTasks: [task({ updated_at: "not a date" })],
    });
    expect(item.ts).toBe(0);
  });

  it("returns everything when the owner is unknown", () => {
    const items = build({
      dashboards: [canvas({ createdBy: "Grace Hopper" })],
      feedTasks: [task({ created_by: OTHER })],
    });
    expect(items).toHaveLength(2);
  });

  it("filters to the owner for the personal channel", () => {
    const items = build({
      dashboards: [
        canvas({ id: "mine", createdByUuid: ME.uuid }),
        canvas({ id: "theirs", createdByUuid: OTHER.uuid }),
      ],
      feedTasks: [
        task({ id: "mine-task", created_by: ME }),
        task({ id: "their-task", created_by: OTHER }),
      ],
      ownedBy: { uuid: ME.uuid },
    });
    expect(items.map((i) => i.id).sort()).toEqual(["mine", "mine-task"]);
  });

  it("never claims ownership from a matching display name", () => {
    const items = build({
      dashboards: [canvas({ id: "name-twin", createdBy: "Ada Lovelace" })],
      ownedBy: { uuid: ME.uuid },
    });
    expect(items).toEqual([]);
  });

  it("excludes items whose author is unknown from the personal channel", () => {
    const items = build({
      dashboards: [canvas({ id: "orphan", createdBy: undefined })],
      feedTasks: [task({ id: "orphan-task", created_by: null })],
      ownedBy: { uuid: ME.uuid },
    });
    expect(items).toEqual([]);
  });
});

function model(over: Partial<ChannelItemModel> = {}): ChannelItemModel {
  return {
    key: "task:t1",
    kind: "task",
    id: "t1",
    title: "Ship the thing",
    ts: 0,
    pinned: false,
    rawStatus: null,
    authorUser: ME,
    authorName: null,
    authorUuid: ME.uuid,
    templateId: null,
    task: null,
    ...over,
  };
}

describe("filterChannelItems", () => {
  const me = { uuid: ME.uuid };

  it("matches titles case-insensitively", () => {
    const items = [model({ title: "Ship IT" }), model({ title: "Other" })];
    const result = filterChannelItems(items, {
      query: "  ship ",
      createdBy: "anyone",
      status: null,
      me,
    });
    expect(result.map((i) => i.title)).toEqual(["Ship IT"]);
  });

  it.each([
    ["me", ["mine"]],
    ["others", ["theirs"]],
    ["anyone", ["mine", "theirs"]],
  ] as const)("filters createdBy=%s", (createdBy, expected) => {
    const items = [
      model({ id: "mine", authorUser: ME, authorUuid: ME.uuid }),
      model({ id: "theirs", authorUser: OTHER, authorUuid: OTHER.uuid }),
    ];
    const result = filterChannelItems(items, {
      query: "",
      createdBy,
      status: null,
      me,
    });
    expect(result.map((i) => i.id)).toEqual(expected);
  });

  // The backend returns `created_by: null` once a creator is deleted, so an
  // item with no uuid is "unknown", not "someone else".
  it.each(["me", "others"] as const)(
    "keeps a creator-less item out of createdBy=%s",
    (createdBy) => {
      const items = [
        model({ id: "orphan", authorUser: null, authorUuid: null }),
      ];
      const result = filterChannelItems(items, {
        query: "",
        createdBy,
        status: null,
        me,
      });
      expect(result).toEqual([]);
    },
  );

  it("filters by run status, including not_started", () => {
    const items = [
      model({ id: "fresh", rawStatus: "not_started" }),
      model({ id: "done", rawStatus: "completed" }),
    ];
    const result = filterChannelItems(items, {
      query: "",
      createdBy: "anyone",
      status: "not_started",
      me,
    });
    expect(result.map((i) => i.id)).toEqual(["fresh"]);
  });

  it("excludes canvases when a run status is selected", () => {
    const items = [model({ kind: "canvas", rawStatus: null })];
    const result = filterChannelItems(items, {
      query: "",
      createdBy: "anyone",
      status: "completed",
      me,
    });
    expect(result).toEqual([]);
  });
});
