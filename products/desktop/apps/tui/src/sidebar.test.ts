import type { Task, TaskRun } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  activeWorkspace,
  initialLayout,
  openTask,
  splitFocused,
} from "./layout";
import {
  activateRow,
  indicatorFor,
  moveSelection,
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
  it("lists single-pane workspaces as tasks and split ones as groups, above Work", () => {
    let layout = openTask(initialLayout(), "a");
    layout = openTask(splitFocused(layout, "row"), "b");
    layout = openTask(layout, "c");
    const work = page({ tasks: [task("a"), task("b"), task("c")] });

    expect(
      labels(
        sidebarRows({ layout, work, collapsed: new Set(), working: new Set() }),
      ),
    ).toEqual([
      "# Tasks",
      "v Workspace 1",
      "  Task a",
      "  Task b",
      "Task c",
      "# Work",
      "Task a",
      "Task b",
      "Task c",
    ]);
  });

  it("hides a collapsed workspace's tasks", () => {
    const layout = openTask(
      splitFocused(openTask(initialLayout(), "a"), "row"),
      "b",
    );
    const rows = sidebarRows({
      layout,
      work: page(),
      collapsed: new Set([layout.workspaces[0].id]),
      working: new Set(),
    });
    expect(labels(rows).slice(0, 3)).toEqual([
      "# Tasks",
      "> Workspace 1",
      "# Work",
    ]);
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
  ])("Work section when %s", (_, work, expected) => {
    const rows = sidebarRows({
      layout: initialLayout(),
      work,
      collapsed: new Set(),
      working: new Set(),
    });
    expect(labels(rows).slice(labels(rows).indexOf("# Work") + 1)).toEqual(
      expected,
    );
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
  // Tasks, Workspace 1, a, b, Work, a, z, View more

  it.each([
    ["down past a heading", 3, 1, 5],
    ["up past a heading", 5, -1, 3],
    ["down at the end", 7, 1, 7],
    ["up at the start", 1, -1, 1],
  ])("moves %s", (_, from, step, to) => {
    expect(moveSelection(rows, from, step as 1 | -1)).toBe(to);
  });

  it("jumps to an open pane, opens a Work task, and asks for more", () => {
    const toPane = activateRow(layout, rows[2]);
    expect(toPane !== "viewMore" && activeWorkspace(toPane).focusedPaneId).toBe(
      rows[2].kind === "task" && rows[2].paneId,
    );

    const opened = activateRow(layout, rows[6]);
    expect(opened !== "viewMore" && opened.workspaces).toHaveLength(2);

    expect(activateRow(layout, rows[7])).toBe("viewMore");
  });
});
