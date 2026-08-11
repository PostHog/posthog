import type { Task } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  ATTENTION_GROUP_KEY,
  buildTaskListItems,
  dateGroupKey,
  NO_REPO_LABEL,
  relativeDateGroup,
  repoGroupKey,
} from "./taskListItems";

const NOW = new Date("2026-06-15T12:00:00Z").getTime();

function daysAgo(days: number): string {
  return new Date(NOW - days * 86_400_000).toISOString();
}

function makeTask(
  id: string,
  overrides: { repository?: string | null; updatedAt?: string } = {},
): Task {
  const updatedAt = overrides.updatedAt ?? daysAgo(0);
  return {
    id,
    task_number: 1,
    slug: id,
    title: id,
    description: "",
    repository: overrides.repository ?? null,
    created_at: updatedAt,
    updated_at: updatedAt,
    origin_product: "code",
  } as Task;
}

function ids(items: ReturnType<typeof buildTaskListItems>): string[] {
  return items.map((item) =>
    item.type === "task" ? item.task.id : item.groupKey,
  );
}

function build(
  tasks: Task[],
  organizeMode: "by-project" | "chronological",
  collapsed: string[] = [],
  awaitingInputTaskIds?: string[],
) {
  return buildTaskListItems({
    tasks,
    organizeMode,
    sortMode: "updated",
    collapsedGroupKeys: new Set(collapsed),
    awaitingInputTaskIds: awaitingInputTaskIds
      ? new Set(awaitingInputTaskIds)
      : undefined,
    now: NOW,
  });
}

describe("relativeDateGroup", () => {
  it.each([
    { days: 0, expected: "Today" },
    { days: 1, expected: "Yesterday" },
    { days: 3, expected: "This week" },
    { days: 10, expected: "This month" },
    { days: 90, expected: "Earlier" },
  ])("puts a task from $days days ago in $expected", ({ days, expected }) => {
    expect(relativeDateGroup(NOW - days * 86_400_000, NOW)).toBe(expected);
  });
});

describe("buildTaskListItems by project", () => {
  const tasks = [
    makeTask("old-repo-task", {
      repository: "posthog/old",
      updatedAt: daysAgo(5),
    }),
    makeTask("fresh", { repository: "posthog/new", updatedAt: daysAgo(0) }),
    makeTask("stale", { repository: "posthog/new", updatedAt: daysAgo(2) }),
    makeTask("orphan"),
  ];

  it("groups by repository, newest group first, with no-repo last", () => {
    expect(ids(build(tasks, "by-project"))).toEqual([
      repoGroupKey("posthog/new"),
      "fresh",
      "stale",
      repoGroupKey("posthog/old"),
      "old-repo-task",
      repoGroupKey(NO_REPO_LABEL),
      "orphan",
    ]);
  });

  it("counts every task in a group even when it is collapsed", () => {
    const items = build(tasks, "by-project", [repoGroupKey("posthog/new")]);

    expect(ids(items)).toEqual([
      repoGroupKey("posthog/new"),
      repoGroupKey("posthog/old"),
      "old-repo-task",
      repoGroupKey(NO_REPO_LABEL),
      "orphan",
    ]);
    expect(items[0]).toMatchObject({ count: 2, collapsed: true });
  });

  it("keeps every other group expanded and ordered when one collapses", () => {
    const items = build(tasks, "by-project", [repoGroupKey("posthog/old")]);

    expect(ids(items)).toEqual([
      repoGroupKey("posthog/new"),
      "fresh",
      "stale",
      repoGroupKey("posthog/old"),
      repoGroupKey(NO_REPO_LABEL),
      "orphan",
    ]);
  });

  it("treats a blank repository as the no-repository group", () => {
    const items = build(
      [makeTask("blank", { repository: "  " })],
      "by-project",
    );

    expect(items[0]).toMatchObject({
      type: "repo-header",
      repoLabel: NO_REPO_LABEL,
    });
  });
});

describe("buildTaskListItems chronologically", () => {
  const tasks = [
    makeTask("last-month", { updatedAt: daysAgo(20) }),
    makeTask("today", { updatedAt: daysAgo(0) }),
    makeTask("yesterday", { updatedAt: daysAgo(1) }),
  ];

  it("orders buckets newest first and omits empty ones", () => {
    expect(ids(build(tasks, "chronological"))).toEqual([
      dateGroupKey("Today"),
      "today",
      dateGroupKey("Yesterday"),
      "yesterday",
      dateGroupKey("This month"),
      "last-month",
    ]);
  });

  it("hides only the collapsed bucket's tasks", () => {
    expect(
      ids(build(tasks, "chronological", [dateGroupKey("Yesterday")])),
    ).toEqual([
      dateGroupKey("Today"),
      "today",
      dateGroupKey("Yesterday"),
      dateGroupKey("This month"),
      "last-month",
    ]);
  });

  it("namespaces group keys so a repo cannot collapse a date bucket", () => {
    const named = [makeTask("t", { repository: "Today" })];

    expect(ids(build(named, "by-project", [dateGroupKey("Today")]))).toEqual([
      repoGroupKey("Today"),
      "t",
    ]);
  });
});

describe("buildTaskListItems needs-attention group", () => {
  const tasks = [
    makeTask("waiting", { repository: "posthog/a", updatedAt: daysAgo(20) }),
    makeTask("also-waiting", {
      repository: "posthog/b",
      updatedAt: daysAgo(0),
    }),
    makeTask("busy", { repository: "posthog/a", updatedAt: daysAgo(1) }),
  ];
  const awaiting = ["waiting", "also-waiting"];

  it.each([
    {
      organizeMode: "by-project" as const,
      expected: [
        ATTENTION_GROUP_KEY,
        "also-waiting",
        "waiting",
        repoGroupKey("posthog/a"),
        "busy",
      ],
    },
    {
      organizeMode: "chronological" as const,
      expected: [
        ATTENTION_GROUP_KEY,
        "also-waiting",
        "waiting",
        dateGroupKey("Yesterday"),
        "busy",
      ],
    },
  ])(
    "pins awaiting tasks above every other group, newest first ($organizeMode)",
    ({ organizeMode, expected }) => {
      expect(ids(build(tasks, organizeMode, [], awaiting))).toEqual(expected);
    },
  );

  it("shows the count and starts expanded", () => {
    expect(build(tasks, "chronological", [], awaiting)[0]).toMatchObject({
      type: "attention-header",
      label: "Needs attention",
      count: 2,
      collapsed: false,
    });
  });

  it("keeps its count and drops its rows once collapsed", () => {
    const items = build(
      tasks,
      "chronological",
      [ATTENTION_GROUP_KEY],
      awaiting,
    );

    expect(ids(items)).toEqual([
      ATTENTION_GROUP_KEY,
      dateGroupKey("Yesterday"),
      "busy",
    ]);
    expect(items[0]).toMatchObject({ count: 2, collapsed: true });
  });

  it("omits the group when nothing is awaiting", () => {
    expect(ids(build(tasks, "chronological", [], []))).toEqual([
      dateGroupKey("Today"),
      "also-waiting",
      dateGroupKey("Yesterday"),
      "busy",
      dateGroupKey("This month"),
      "waiting",
    ]);
  });

  it("ignores awaiting ids for tasks the list is not showing", () => {
    expect(
      ids(build([makeTask("solo")], "chronological", [], ["ghost"])),
    ).toEqual([dateGroupKey("Today"), "solo"]);
  });
});
