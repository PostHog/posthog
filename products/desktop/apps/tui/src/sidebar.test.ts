import type { Task, TaskRun } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  activeWorkspace,
  focusPane,
  initialLayout,
  type LayoutState,
  newChat,
  openTask,
  paneIds,
  splitFocused,
} from "./layout";
import {
  activateRow,
  cursorIndex,
  indicatorFor,
  moveSelection,
  selectionKey,
  sidebarRows,
  type WorkPage,
} from "./sidebar";

const task = (id: string, run?: Partial<TaskRun>): Task =>
  ({
    id,
    title: `Task ${id}`,
    latest_run: run
      ? ({ status: "in_progress", state: {}, ...run } as TaskRun)
      : undefined,
  }) as Task;

const page = (overrides: Partial<WorkPage> = {}): WorkPage => ({
  tasks: [],
  hasMore: false,
  loadingMore: false,
  error: null,
  ...overrides,
});

const labels = (rows: ReturnType<typeof sidebarRows>): string[] =>
  rows.map((row) => {
    switch (row.kind) {
      case "heading":
        return `# ${row.label}`;
      case "section":
        return `## ${row.label}`;
      case "today":
        return "Today";
      case "gap":
        return "";
      case "workspace":
        return `${row.expanded ? "v" : ">"} ${row.label}`;
      case "task":
        return `${row.nested ? "  " : ""}${row.title}`;
      default:
        return `[${row.kind}]`;
    }
  });

describe("sidebarRows", () => {
  const rowsFor = (
    layout: LayoutState,
    work: WorkPage,
    collapsed = new Set<string>(),
  ) => labels(sidebarRows({ layout, work, collapsed, working: new Set() }));

  it("keeps one Work list, with split tasks in their workspace and in All tasks", () => {
    let layout = openTask(initialLayout(), "a");
    layout = openTask(splitFocused(layout, "row"), "b");
    layout = openTask(layout, "c");

    expect(
      rowsFor(layout, page({ tasks: [task("a"), task("b"), task("c")] })),
    ).toEqual([
      "# Work",
      "Today",
      "New chat",
      "",
      "v Workspace 1",
      "  Task a",
      "  Task b",
      "",
      "## All tasks",
      "Task a",
      "Task b",
      "Task c",
    ]);
    const rows = sidebarRows({
      layout,
      work: page({ tasks: [task("a"), task("b"), task("c")] }),
      collapsed: new Set(),
      working: new Set(),
    });
    expect(rows.slice(4, 7)).toMatchObject([
      { kind: "workspace", size: 2 },
      { kind: "task", nested: true, last: false },
      { kind: "task", nested: true, last: true },
    ]);
  });

  it("lists Today and New chat above the work, each opening the main view its own way", () => {
    const empty = initialLayout();
    const rows = sidebarRows({
      layout: empty,
      work: page({ tasks: [task("a")] }),
      collapsed: new Set(),
      working: new Set(),
    });
    expect(labels(rows)).toEqual([
      "# Work",
      "Today",
      "New chat",
      "",
      "## All tasks",
      "Task a",
    ]);
    const mainPane = activeWorkspace(empty).focusedPaneId;
    expect(rows[1]).toEqual({ kind: "today", paneId: null });
    expect(rows[2]).toMatchObject({
      kind: "task",
      taskId: null,
      paneId: mainPane,
    });

    const today = activateRow(empty, rows[1]);
    expect(today !== "viewMore" && activeWorkspace(today).root).toMatchObject({
      taskId: null,
      today: true,
    });
    const [todayRow, newChatRow] = sidebarRows({
      layout: today as LayoutState,
      work: page({ tasks: [task("a")] }),
      collapsed: new Set(),
      working: new Set(),
    }).slice(1, 3);
    expect(todayRow).toEqual({ kind: "today", paneId: mainPane });
    expect(newChatRow).toMatchObject({
      kind: "task",
      taskId: null,
      paneId: null,
    });
    const fresh = activateRow(today as LayoutState, newChatRow);
    expect(fresh !== "viewMore" && activeWorkspace(fresh).root).toMatchObject({
      taskId: null,
      today: undefined,
    });
  });

  it("puts each workspace above All tasks with a gap after it", () => {
    let layout = openTask(initialLayout(), "a");
    layout = openTask(splitFocused(layout, "row"), "b");
    layout = newChat(layout);
    layout = openTask(layout, "c");
    layout = openTask(splitFocused(layout, "row"), "d");

    expect(
      rowsFor(
        layout,
        page({ tasks: ["a", "b", "c", "d", "e"].map((id) => task(id)) }),
      ),
    ).toEqual([
      "# Work",
      "Today",
      "New chat",
      "",
      "v Workspace 1",
      "  Task a",
      "  Task b",
      "",
      "v Workspace 2",
      "  Task c",
      "  Task d",
      "",
      "## All tasks",
      "Task a",
      "Task b",
      "Task c",
      "Task d",
      "Task e",
    ]);
  });

  it("titles an open task outside the recent page from the tasks fetched for it", () => {
    const layout = openTask(initialLayout(), "old");
    const rows = sidebarRows({
      layout,
      work: page({ tasks: [task("a")] }),
      collapsed: new Set(),
      working: new Set(),
      known: new Map([["old", task("old")]]),
    });
    expect(labels(rows)).toEqual([
      "# Work",
      "Today",
      "New chat",
      "",
      "## All tasks",
      "Task old",
      "Task a",
    ]);
  });

  it("shows only split workspaces, named from the saved layout, while the list loads", () => {
    let layout = splitFocused(
      openTask(initialLayout(), "a", "Fix the flaky test"),
      "row",
    );
    layout = focusPane(layout, paneIds(activeWorkspace(layout).root)[0]);
    layout = openTask(layout, "m", "Main view task");
    const rows = sidebarRows({
      layout,
      work: page({ tasks: null }),
      collapsed: new Set(),
      working: new Set(),
    });

    expect(labels(rows)).toEqual([
      "# Work",
      "Today",
      "New chat",
      "",
      "v Workspace 1",
      "  Fix the flaky test",
      "  New chat",
      "",
      "## All tasks",
      "[loading]",
    ]);
    expect(rows[5]).toMatchObject({ kind: "task", indicator: null });
  });

  it("says how to sign in instead of loading work while signed out", () => {
    const rows = sidebarRows({
      layout: initialLayout(),
      work: page({ tasks: null }),
      collapsed: new Set(),
      working: new Set(),
      signedIn: false,
    });
    expect(labels(rows)).toEqual([
      "# Work",
      "Today",
      "New chat",
      "",
      "## All tasks",
      "[signedOut]",
    ]);
  });

  it("hides a collapsed workspace's tasks", () => {
    const layout = openTask(
      splitFocused(openTask(initialLayout(), "a"), "row"),
      "b",
    );
    expect(rowsFor(layout, page(), new Set([layout.workspaces[0].id]))).toEqual(
      [
        "# Work",
        "Today",
        "New chat",
        "",
        "> Workspace 1",
        "",
        "## All tasks",
        "[empty]",
      ],
    );
  });

  it.each([
    ["loading the first page", page({ tasks: null }), ["[loading]"]],
    ["empty", page(), ["[empty]"]],
    [
      "more to load",
      page({ tasks: [task("a")], hasMore: true }),
      ["Task a", "[viewMore]"],
    ],
    [
      "loading more",
      page({ tasks: [task("a")], hasMore: true, loadingMore: true }),
      ["Task a", "[loading]"],
    ],
    ["failed", page({ tasks: null, error: "boom" }), ["[error]"]],
  ])("Work list when %s", (_, work, expected) => {
    expect(rowsFor(initialLayout(), work).slice(5)).toEqual(expected);
  });
});

describe("indicatorFor", () => {
  it.each([
    ["mid-turn", task("a", { status: "in_progress" }), "working", "working"],
    [
      "a turn that ended unseen",
      task("a", { status: "in_progress" }),
      "waiting",
      "waiting",
    ],
    [
      "failed, though its turn ended unseen",
      task("a", { status: "failed" }),
      "waiting",
      "failed",
    ],
    ["queued", task("a", { status: "queued" }), "idle", "alive"],
    [
      "running with a live sandbox",
      task("a", { status: "in_progress" }),
      "idle",
      "alive",
    ],
    [
      "running with a stopped sandbox",
      task("a", { status: "in_progress", state: { sandbox_alive: false } }),
      "idle",
      "asleep",
    ],
    ["failed", task("a", { status: "failed" }), "idle", "failed"],
    ["completed", task("a", { status: "completed" }), "idle", "asleep"],
    ["never run", task("a"), "idle", "asleep"],
  ])("%s", (_, subject, turn, expected) => {
    expect(indicatorFor(subject, turn === "working", turn === "waiting")).toBe(
      expected,
    );
  });
});

describe("sidebar selection", () => {
  const layout = openTask(
    splitFocused(openTask(initialLayout(), "a"), "row"),
    "b",
  );
  const rows = sidebarRows({
    layout,
    work: page({ tasks: [task("a"), task("z")], hasMore: true }),
    collapsed: new Set(),
    working: new Set(),
  });
  // Work, Today, New chat, gap, Workspace 1, a, b, gap, All tasks, a, z, View more

  it.each([
    ["down", 5, 1, 6],
    ["up past the workspace heading to New chat", 5, -1, 2],
    ["down past the gap and All tasks", 6, 1, 9],
    ["down at the end", 11, 1, 11],
    ["up past All tasks and the gap", 9, -1, 6],
  ])("moves %s", (_, from, step, to) => {
    expect(moveSelection(rows, from, step as 1 | -1)).toBe(to);
  });

  it("jumps to an open pane, opens a Work task, and asks for more", () => {
    const paneOfA = rows[5].kind === "task" && rows[5].paneId;
    for (const row of [rows[5], rows[9]]) {
      const toPane = activateRow(layout, row);
      expect(
        toPane !== "viewMore" && activeWorkspace(toPane).focusedPaneId,
      ).toBe(paneOfA);
    }

    const opened = activateRow(layout, rows[10]);
    expect(opened !== "viewMore" && opened.workspaces).toHaveLength(2);

    expect(activateRow(layout, rows[11])).toBe("viewMore");
  });

  it("tells a split task's two rows apart, so the cursor stays on the one picked", () => {
    expect(cursorIndex(rows, selectionKey(rows[5]))).toBe(5);
    expect(cursorIndex(rows, selectionKey(rows[9]))).toBe(9);
  });

  it("keeps the cursor on the same task when opening it moves rows around", () => {
    const main = openTask(initialLayout(), "old");
    const work = page({ tasks: [task("a"), task("b")] });
    const before = sidebarRows({
      layout: main,
      work,
      collapsed: new Set(),
      working: new Set(),
      known: new Map([["old", task("old")]]),
    });
    const onA = before.findIndex(
      (row) => row.kind === "task" && row.taskId === "a",
    );
    const opened = activateRow(main, before[onA]);

    const after = sidebarRows({
      layout: opened === "viewMore" ? main : opened,
      work,
      collapsed: new Set(),
      working: new Set(),
    });

    const key = selectionKey(before[onA]);
    expect(after.findIndex((row) => selectionKey(row) === key)).toBe(
      after.findIndex((row) => row.kind === "task" && row.taskId === "a"),
    );
    expect(after.findIndex((row) => selectionKey(row) === key)).not.toBe(onA);
  });

  it("keeps a local chat in its place as the cursor opens the tasks past it", () => {
    const active = (minutesAgo: number): string =>
      new Date(Date.UTC(2026, 0, 1, 12, 60 - minutesAgo)).toISOString();
    const at = (id: string, minutesAgo: number): Task =>
      ({ ...task(id), last_activity_at: active(minutesAgo) }) as Task;
    const work = page({ tasks: [at("a", 10), at("b", 30)] });
    const local = {
      active: new Map([["mine", Date.parse(active(20))]]),
      running: new Set(["mine"]),
    };
    const rowsIn = (layout: LayoutState) =>
      sidebarRows({
        layout,
        work,
        collapsed: new Set(),
        working: new Set(),
        known: new Map([["mine", at("mine", 60)]]),
        local,
      });
    let layout = openTask(initialLayout(), "mine");
    let rows = rowsIn(layout);
    expect(labels(rows)).toEqual([
      "# Work",
      "Today",
      "New chat",
      "",
      "## All tasks",
      "Task a",
      "Task mine",
      "Task b",
    ]);
    expect(rows[6]).toMatchObject({ local: true, indicator: "alive" });

    // Down to b, then up past the local chat to a, each opening in the main view.
    let cursor = selectionKey(rows[6]);
    for (const step of [1, -1, -1] as const) {
      const index = moveSelection(rows, cursorIndex(rows, cursor), step);
      cursor = selectionKey(rows[index]);
      const opened = activateRow(layout, rows[index]);
      layout = opened === "viewMore" ? layout : opened;
      rows = rowsIn(layout);
      expect(labels(rows)).toEqual([
        "# Work",
        "Today",
        "New chat",
        "",
        "## All tasks",
        "Task a",
        "Task mine",
        "Task b",
      ]);
    }
    expect(cursor).toBe("task:a");
  });

  it("lists a local chat outside the page only when it is newer than the page's oldest task", () => {
    const at = (id: string, ms: number): Task =>
      ({ ...task(id), last_activity_at: new Date(ms).toISOString() }) as Task;
    const rows = sidebarRows({
      layout: initialLayout(),
      work: page({ tasks: [at("a", 3_000), at("b", 1_000)], hasMore: true }),
      collapsed: new Set(),
      working: new Set(),
      known: new Map([
        ["new", at("new", 0)],
        ["old", at("old", 0)],
      ]),
      local: {
        active: new Map([
          ["new", 2_000],
          ["old", 500],
        ]),
        running: new Set(),
      },
    });

    expect(labels(rows)).toEqual([
      "# Work",
      "Today",
      "New chat",
      "",
      "## All tasks",
      "Task a",
      "Task new",
      "Task b",
      "[viewMore]",
    ]);
    expect(rows[6]).toMatchObject({ local: true, indicator: "asleep" });
  });

  it("starts the cursor on the first row it can select, not the heading", () => {
    expect(cursorIndex(rows, null)).toBe(1);
    expect(cursorIndex(rows, selectionKey(rows[9]))).toBe(9);
    expect(cursorIndex(rows, "task:gone")).toBe(1);
  });
});
