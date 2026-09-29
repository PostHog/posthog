import type { Task, TaskRun } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  activeWorkspace,
  focusPane,
  focusSidebar,
  initialLayout,
  type LayoutState,
  openTask,
  paneIds,
  splitFocused,
} from "./layout";
import {
  activateRow,
  cursorIndex,
  indicatorFor,
  moveSelection,
  previewRow,
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

  it("keeps one Work list and moves split tasks into their workspace", () => {
    let layout = openTask(initialLayout(), "a");
    layout = openTask(splitFocused(layout, "row"), "b");
    layout = openTask(layout, "c");

    expect(
      rowsFor(layout, page({ tasks: [task("a"), task("b"), task("c")] })),
    ).toEqual(["# Work", "v Workspace 1", "  Task a", "  Task b", "Task c"]);
    const rows = sidebarRows({
      layout,
      work: page({ tasks: [task("a"), task("b"), task("c")] }),
      collapsed: new Set(),
      working: new Set(),
    });
    expect(rows.slice(1, 4)).toMatchObject([
      { kind: "workspace", size: 2 },
      { kind: "task", nested: true, last: false },
      { kind: "task", nested: true, last: true },
    ]);
  });

  it("puts a new chat at the top", () => {
    expect(rowsFor(initialLayout(), page({ tasks: [task("a")] }))).toEqual([
      "# Work",
      "New chat",
      "Task a",
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
    expect(labels(rows)).toEqual(["# Work", "Task old", "Task a"]);
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
      "v Workspace 1",
      "  Fix the flaky test",
      "  New chat",
      "[loading]",
    ]);
    expect(rows[2]).toMatchObject({ kind: "task", indicator: null });
  });

  it("hides a collapsed workspace's tasks", () => {
    const layout = openTask(
      splitFocused(openTask(initialLayout(), "a"), "row"),
      "b",
    );
    expect(rowsFor(layout, page(), new Set([layout.workspaces[0].id]))).toEqual(
      ["# Work", "> Workspace 1", "[empty]"],
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
    expect(rowsFor(initialLayout(), work).slice(2)).toEqual(expected);
  });
});

describe("indicatorFor", () => {
  it.each([
    ["mid-turn", task("a", { status: "in_progress" }), true, "working"],
    ["queued", task("a", { status: "queued" }), false, "alive"],
    [
      "running with a live sandbox",
      task("a", { status: "in_progress" }),
      false,
      "alive",
    ],
    [
      "running with a stopped sandbox",
      task("a", { status: "in_progress", state: { sandbox_alive: false } }),
      false,
      "asleep",
    ],
    ["failed", task("a", { status: "failed" }), false, "failed"],
    ["completed", task("a", { status: "completed" }), false, "asleep"],
    ["never run", task("a"), false, "asleep"],
  ])("%s", (_, subject, working, expected) => {
    expect(indicatorFor(subject, working)).toBe(expected);
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
  // Work, Workspace 1, a, b, z, View more

  it.each([
    ["down", 1, 1, 2],
    ["up onto the heading", 1, -1, 1],
    ["down at the end", 5, 1, 5],
    ["up", 4, -1, 3],
  ])("moves %s", (_, from, step, to) => {
    expect(moveSelection(rows, from, step as 1 | -1)).toBe(to);
  });

  it("jumps to an open pane, opens a Work task, and asks for more", () => {
    const toPane = activateRow(layout, rows[2]);
    expect(toPane !== "viewMore" && activeWorkspace(toPane).focusedPaneId).toBe(
      rows[2].kind === "task" && rows[2].paneId,
    );

    const opened = activateRow(layout, rows[4]);
    expect(opened !== "viewMore" && opened.workspaces).toHaveLength(2);

    expect(activateRow(layout, rows[5])).toBe("viewMore");
  });

  it("previews the chat under the cursor while the sidebar keeps focus", () => {
    const inWorkspace = previewRow(focusSidebar(layout), rows[2]);
    expect(inWorkspace.focus).toBe("sidebar");
    expect(activeWorkspace(inWorkspace).focusedPaneId).toBe(
      rows[2].kind === "task" && rows[2].paneId,
    );

    const outside = previewRow(focusSidebar(layout), rows[4]);
    expect(outside.focus).toBe("sidebar");
    expect(outside.workspaces).toHaveLength(2);

    expect(previewRow(layout, rows[5])).toBe(layout);
  });

  it("keeps the cursor on the same task when previewing moves rows around", () => {
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

    const after = sidebarRows({
      layout: previewRow(main, before[onA]),
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

  it("starts the cursor on the first row it can select, not the heading", () => {
    expect(cursorIndex(rows, null)).toBe(1);
    expect(cursorIndex(rows, selectionKey(rows[4]))).toBe(4);
    expect(cursorIndex(rows, "task:gone")).toBe(1);
  });
});
