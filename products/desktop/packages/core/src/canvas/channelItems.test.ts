import type { Task, UserBasic } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  buildChannelItems,
  type ChannelItemFilters,
  type ChannelItemModel,
  type ChannelItemSort,
  channelItemSources,
  DEFAULT_CHANNEL_ITEM_FILTERS,
  filterChannelItems,
  groupChannelItems,
  sortChannelItems,
} from "./channelItems";
import type { DashboardRecord } from "./dashboardSchemas";

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

function canvas(over: Partial<DashboardRecord> = {}): DashboardRecord {
  return {
    id: "d1",
    channelId: "c1",
    name: "Canvas",
    kind: "freeform" as const,
    description: "",
    templateId: "freeform",
    context: "",
    createdAt: 0,
    updatedAt: 1_000,
    ...over,
  };
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

  it("ranks a session by its activity, not by when its row was last written", () => {
    const items = build({
      feedTasks: [
        task({
          id: "still-running",
          created_at: new Date(1_000).toISOString(),
          updated_at: new Date(1_000).toISOString(),
          last_activity_at: new Date(9_000).toISOString(),
        }),
        task({
          id: "filed-later",
          created_at: new Date(5_000).toISOString(),
          updated_at: new Date(5_000).toISOString(),
          last_activity_at: new Date(5_000).toISOString(),
        }),
      ],
    });
    expect(sortChannelItems(items, "recent").map((i) => i.id)).toEqual([
      "still-running",
      "filed-later",
    ]);
    expect(sortChannelItems(items, "created").map((i) => i.id)).toEqual([
      "filed-later",
      "still-running",
    ]);
  });

  it("treats an unparseable updated_at as epoch rather than NaN", () => {
    const [item] = build({
      feedTasks: [task({ updated_at: "not a date" })],
    });
    expect(item.ts).toBe(0);
  });

  // The filters ask about facts that only exist once the renderer's state is
  // folded in, so each has to survive the build rather than being read off the
  // task alone.
  it.each([
    {
      what: "a worktree, which is a local checkout",
      mode: "worktree" as const,
      runEnvironment: null,
      expected: "local",
    },
    {
      what: "a workspace we can see, over the run's own claim",
      mode: "local" as const,
      runEnvironment: "cloud" as const,
      expected: "local",
    },
    {
      what: "the run, when there is no workspace",
      mode: undefined,
      runEnvironment: "cloud" as const,
      expected: "cloud",
    },
    {
      what: "neither, which leaves the session unplaced",
      mode: undefined,
      runEnvironment: null,
      expected: null,
    },
  ])("places a session by $what", ({ mode, runEnvironment, expected }) => {
    const [item] = build({
      feedTasks: [
        task({
          latest_run: runEnvironment
            ? ({ environment: runEnvironment } as Task["latest_run"])
            : undefined,
        }),
      ],
      sessionFacts: {
        needsInputTaskIds: NONE,
        viewedTimestamps: {},
        workspaceByTaskId: new Map(mode ? [["t1", { mode }]] : []),
      },
    });
    expect(item.environment).toBe(expected);
  });

  it("resolves a session's repository and branch once, checkout first", () => {
    const [item] = build({
      feedTasks: [task({ id: "t1", repository: "PostHog/code" })],
      sessionFacts: {
        needsInputTaskIds: NONE,
        viewedTimestamps: {},
        workspaceByTaskId: new Map([
          ["t1", { folderPath: "/src/code", branch: "posthog/session-list" }],
        ]),
      },
    });

    expect(item.repository).toEqual({
      key: "posthog/code",
      label: "PostHog/code",
    });
    expect(item.branch).toBe("posthog/session-list");
  });

  it("does not treat a scratch workspace's folder as a repository", () => {
    const [item] = build({
      feedTasks: [task({ id: "t1" })],
      sessionFacts: {
        needsInputTaskIds: NONE,
        viewedTimestamps: {},
        workspaceByTaskId: new Map([
          ["t1", { folderPath: "/scratch/t1", isScratch: true }],
        ]),
      },
    });

    expect(item.repository).toBeNull();
  });

  it("reads a filed session's source, and none for one started here", () => {
    const items = build({
      feedTasks: [
        task({ id: "filed", origin_product: "slack" }),
        task({ id: "own", origin_product: "user_created" }),
      ],
    });
    expect(items.map((i) => i.source)).toEqual(["slack", null]);
  });

  it("marks the sessions asking for input and the ones you haven't read", () => {
    const items = build({
      feedTasks: [
        task({ id: "asking" }),
        task({ id: "unread" }),
        task({ id: "quiet" }),
      ],
      sessionFacts: {
        needsInputTaskIds: new Set(["asking"]),
        // Read before it last moved, so only this one counts as unread. A task
        // never opened has no timestamp and is not unread.
        viewedTimestamps: {
          unread: { lastViewedAt: 1_000, lastActivityAt: null },
        },
        workspaceByTaskId: new Map(),
      },
    });
    expect(items.map((i) => [i.id, i.needsInput, i.unread])).toEqual([
      ["asking", true, false],
      ["unread", false, true],
      ["quiet", false, false],
    ]);
  });

  it("marks a session unread from activity its row write time didn't capture", () => {
    const [item] = build({
      feedTasks: [
        task({
          id: "streamed",
          updated_at: new Date(1_000).toISOString(),
          last_activity_at: new Date(3_000).toISOString(),
        }),
      ],
      sessionFacts: {
        needsInputTaskIds: NONE,
        viewedTimestamps: {
          streamed: { lastViewedAt: 2_000, lastActivityAt: null },
        },
        workspaceByTaskId: new Map(),
      },
    });
    expect(item.unread).toBe(true);
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
    createdAt: 0,
    pinned: false,
    rawStatus: null,
    environment: null,
    source: null,
    needsInput: false,
    unread: false,
    authorUser: ME,
    authorName: null,
    authorUuid: ME.uuid,
    templateId: null,
    repository: null,
    branch: null,
    task: null,
    ...over,
  };
}

function filters(over: Partial<ChannelItemFilters> = {}): ChannelItemFilters {
  return { ...DEFAULT_CHANNEL_ITEM_FILTERS, ...over };
}

describe("filterChannelItems", () => {
  const me = { uuid: ME.uuid };

  it("matches titles case-insensitively", () => {
    const items = [model({ title: "Ship IT" }), model({ title: "Other" })];
    const result = filterChannelItems(items, {
      query: "  ship ",
      filters: filters(),
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
      filters: filters({ createdBy }),
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
        filters: filters({ createdBy }),
        me,
      });
      expect(result).toEqual([]);
    },
  );

  const CANDIDATES = [
    model({ id: "asking", needsInput: true }),
    model({ id: "unread", unread: true }),
    model({ id: "pinned", pinned: true }),
    model({ id: "local", environment: "local" }),
    model({ id: "cloud", environment: "cloud" }),
    model({ id: "from-slack", source: "slack" }),
    model({ id: "quiet" }),
  ];

  it.each([
    { filter: { attention: "needs_input" }, kept: ["asking"] },
    { filter: { attention: "unread" }, kept: ["unread"] },
    { filter: { pinned: "pinned" }, kept: ["pinned"] },
    { filter: { environment: "local" }, kept: ["local"] },
    { filter: { environment: "cloud" }, kept: ["cloud"] },
    { filter: { source: "slack" }, kept: ["from-slack"] },
  ] as const)("keeps only $kept for $filter", ({ filter, kept }) => {
    const result = filterChannelItems(CANDIDATES, {
      query: "",
      filters: filters(filter),
      me,
    });
    expect(result.map((i) => i.id)).toEqual(kept);
  });

  it("narrows on every filter at once", () => {
    const items = [
      model({ id: "match", unread: true, environment: "cloud", pinned: true }),
      model({ id: "not-pinned", unread: true, environment: "cloud" }),
      model({ id: "wrong-place", unread: true, environment: "local" }),
    ];
    const result = filterChannelItems(items, {
      query: "",
      filters: filters({
        attention: "unread",
        environment: "cloud",
        pinned: "pinned",
      }),
      me,
    });
    expect(result.map((i) => i.id)).toEqual(["match"]);
  });
});

describe("channelItemSources", () => {
  it("offers each source once, and nothing for sessions started here", () => {
    const items = [
      model({ id: "a", source: "slack" }),
      model({ id: "b", source: "slack" }),
      model({ id: "c", source: "error_tracking" }),
      model({ id: "d", source: null }),
    ];
    expect(channelItemSources(items)).toEqual(["error_tracking", "slack"]);
  });
});

describe("sortChannelItems", () => {
  const items = [
    model({ id: "middle", title: "B", ts: 2, createdAt: 3 }),
    model({ id: "newest", title: "C", ts: 3, createdAt: 1 }),
    model({ id: "oldest", title: "A", ts: 1, createdAt: 2 }),
  ];

  it.each([
    { sort: "recent", order: ["newest", "middle", "oldest"] },
    { sort: "created", order: ["middle", "oldest", "newest"] },
    { sort: "alpha", order: ["oldest", "middle", "newest"] },
  ] as const)("orders by $sort", ({ sort, order }) => {
    expect(sortChannelItems(items, sort).map((i) => i.id)).toEqual(order);
  });

  // A pin is a request not to lose the thing, and the list is capped — under any
  // sort a pinned session that fell in with the rest could drop off the end.
  it("leads with pins whatever the sort", () => {
    const pinnedLast = [
      ...items,
      model({ id: "pin", title: "Z", ts: 0, createdAt: 0, pinned: true }),
    ];
    for (const sort of ["recent", "created", "alpha"] as const) {
      expect(sortChannelItems(pinnedLast, sort)[0]?.id).toBe("pin");
    }
  });
});

describe("groupChannelItems", () => {
  const NOW = new Date(2026, 6, 29, 12);
  const at = (day: number, hour: number) =>
    new Date(2026, 6, day, hour).getTime();

  function group(items: ChannelItemModel[], sort: ChannelItemSort = "recent") {
    return groupChannelItems(sortChannelItems(items, sort), sort, NOW).map(
      (section) => [section.label, ...section.items.map((i) => i.id)],
    );
  }

  it("files rows under their repository, unnamed ones last, when asked to", () => {
    const withRepo = (id: string, key: string | null, label = "") =>
      model({
        id,
        ts: at(29, 9),
        repository: key ? { key, label } : null,
      });

    expect(
      groupChannelItems(
        [
          withRepo("code-1", "posthog/code", "PostHog/code"),
          withRepo("loose", null),
          withRepo("code-2", "posthog/code", "posthog/code"),
          withRepo("web", "posthog/posthog", "PostHog/posthog"),
        ],
        "recent",
        NOW,
        "repository",
      ).map((section) => [section.label, ...section.items.map((i) => i.id)]),
    ).toEqual([
      ["PostHog/code", "code-1", "code-2"],
      ["PostHog/posthog", "web"],
      ["No repository", "loose"],
    ]);
  });

  it("runs a day's items under one header", () => {
    expect(
      group([
        model({ id: "morning", ts: at(29, 9) }),
        model({ id: "earlier", ts: at(29, 8) }),
        model({ id: "last-night", ts: at(28, 22) }),
      ]),
    ).toEqual([
      ["Today", "morning", "earlier"],
      ["Yesterday", "last-night"],
    ]);
  });

  // The pin is what lifted it out of its day; leaving it in both places would
  // list one session twice.
  it("lists a pin under the pins and nowhere else", () => {
    expect(
      group([
        model({ id: "today", ts: at(29, 9) }),
        model({ id: "kept", ts: at(20, 9), pinned: true }),
      ]),
    ).toEqual([
      ["Pinned", "kept"],
      ["Today", "today"],
    ]);
  });

  // Dating a created-first list by last activity would reopen a day the list
  // had already passed, splitting one day across two headers.
  it("dates a created-first list by when each session started", () => {
    expect(
      group(
        [
          model({ id: "started-today", createdAt: at(29, 9), ts: at(20, 9) }),
          model({ id: "started-friday", createdAt: at(24, 9), ts: at(29, 11) }),
        ],
        "created",
      ),
    ).toEqual([
      ["Today", "started-today"],
      ["Friday", "started-friday"],
    ]);
  });

  // A row can be stamped ahead of this client's clock (skew between whoever
  // wrote it and whoever reads it). Dated on its own it opens a second "Today".
  it("keeps a row stamped in the future under today", () => {
    expect(
      group([
        model({ id: "ahead", ts: at(29, 14) }),
        model({ id: "earlier", ts: at(29, 9) }),
      ]),
    ).toEqual([["Today", "ahead", "earlier"]]);
  });

  it("leaves an alphabetical list undated", () => {
    expect(
      group(
        [
          model({ id: "a", title: "A", ts: at(29, 9) }),
          model({ id: "b", title: "B", ts: at(20, 9) }),
        ],
        "alpha",
      ),
    ).toEqual([[null, "a", "b"]]);
  });
});
