import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  activeWorkspace,
  adoptSharedLayout,
  allPanes,
  assignTask,
  closeFocused,
  cycleFocus,
  expandPane,
  focusPane,
  initialLayout,
  type LayoutNode,
  type LayoutState,
  loadLayout,
  newChat,
  newChatIn,
  openTask,
  optimizeWorkspace,
  paneIds,
  saveLayout,
  splitFocused,
  splitSizes,
} from "./layout";

const focusedTask = (state: LayoutState): string | null => {
  const workspace = activeWorkspace(state);
  const find = (node: typeof workspace.root): string | null | undefined =>
    node.kind === "pane"
      ? node.id === workspace.focusedPaneId
        ? node.taskId
        : undefined
      : node.children.map(find).find((found) => found !== undefined);
  return find(workspace.root) ?? null;
};

describe("layout", () => {
  it("fills the empty starting pane with the first task", () => {
    const state = openTask(initialLayout(), "a");
    expect(state.workspaces).toHaveLength(1);
    expect(focusedTask(state)).toBe("a");
  });

  it("splits right then down around the focused pane and focuses the new pane", () => {
    const right = splitFocused(openTask(initialLayout(), "a"), "row");
    const down = splitFocused(right, "column");
    const { root, focusedPaneId } = activeWorkspace(down);

    expect(root).toMatchObject({
      kind: "split",
      direction: "row",
      children: [
        { kind: "pane", taskId: "a" },
        { kind: "split", direction: "column" },
      ],
    });
    expect(paneIds(root)).toHaveLength(3);
    expect(focusedPaneId).toBe(paneIds(root)[2]);
  });

  it("opens a task in the focused empty pane from a split", () => {
    const state = openTask(
      splitFocused(openTask(initialLayout(), "a"), "row"),
      "b",
    );
    expect(state.workspaces).toHaveLength(1);
    expect(focusedTask(state)).toBe("b");
  });

  it("shows a task that is not open in the main view, replacing what it showed", () => {
    const state = openTask(openTask(initialLayout(), "a"), "b");
    expect(state.workspaces).toHaveLength(1);
    expect(focusedTask(state)).toBe("b");
  });

  it("opens a task from a split in one main view and leaves the split alone", () => {
    let state = openTask(
      splitFocused(openTask(initialLayout(), "a"), "row"),
      "b",
    );
    state = openTask(state, "c");
    state = openTask(state, "d");

    expect(state.workspaces).toHaveLength(2);
    expect(state.workspaces[0].root).toMatchObject({ kind: "split" });
    expect(focusedTask(state)).toBe("d");
  });

  it("clears the main view for a new chat, even from inside a split", () => {
    let state = openTask(
      splitFocused(openTask(initialLayout(), "a"), "row"),
      "b",
    );
    state = newChat(openTask(state, "c"));
    expect(state.workspaces).toHaveLength(2);
    expect(focusedTask(state)).toBeNull();

    state = newChat(focusPane(state, paneIds(state.workspaces[0].root)[0]));
    expect(state.workspaces).toHaveLength(2);
    expect(state.activeWorkspaceId).toBe(state.workspaces[1].id);
  });

  it("gives a /new from a split pane that pane, and from the main view the main view", () => {
    const split = openTask(
      splitFocused(openTask(initialLayout(), "a"), "row"),
      "b",
    );
    const [paneA, paneB] = paneIds(split.workspaces[0].root);
    const fromSplit = newChatIn(split, paneA);
    expect(allPanes(fromSplit).map((pane) => pane.taskId)).toEqual([null, "b"]);
    expect(activeWorkspace(fromSplit).focusedPaneId).toBe(paneA);
    expect(fromSplit.workspaces).toHaveLength(1);

    const withMain = openTask(focusPane(split, paneB), "c");
    const main = withMain.workspaces.find((w) => w.root.kind === "pane");
    const fromMain = newChatIn(withMain, main?.focusedPaneId ?? "");
    expect(allPanes(fromMain).map((pane) => pane.taskId)).toEqual([
      "a",
      "b",
      null,
    ]);
  });

  it("jumps to the workspace and pane of a task that is already open", () => {
    let state = openTask(initialLayout(), "a");
    state = openTask(splitFocused(state, "row"), "b");
    state = openTask(state, "c");
    state = openTask(state, "a");

    expect(state.activeWorkspaceId).toBe(state.workspaces[0].id);
    expect(focusedTask(state)).toBe("a");
    expect(state.focus).toBe("pane");
  });

  it("puts a started chat into the pane it came from, even after focus moved", () => {
    let state = splitFocused(initialLayout(), "row");
    const [first, second] = paneIds(activeWorkspace(state).root);
    state = focusPane(state, second);

    state = assignTask(state, first, "new");

    const workspace = activeWorkspace(state);
    expect(workspace.root).toMatchObject({
      children: [
        { id: first, taskId: "new" },
        { id: second, taskId: null },
      ],
    });
    expect(workspace.focusedPaneId).toBe(second);
  });

  it("closes the focused pane, collapses the split and focuses the previous pane", () => {
    const state = closeFocused(
      splitFocused(openTask(initialLayout(), "a"), "row"),
    );
    expect(state).not.toBe("quit");
    const { root } = activeWorkspace(state as LayoutState);
    expect(root).toMatchObject({ kind: "pane", taskId: "a" });
  });

  it("closing the main view moves to a split, and closing the very last pane quits", () => {
    let state = openTask(
      splitFocused(openTask(initialLayout(), "a"), "row"),
      "b",
    );
    state = openTask(state, "c");

    state = closeFocused(state) as LayoutState;
    expect(state.workspaces).toHaveLength(1);
    expect(focusedTask(state)).toBe("b");
    state = closeFocused(state) as LayoutState;
    expect(focusedTask(state)).toBe("a");
    expect(closeFocused(state)).toBe("quit");
  });

  it.each([
    ["tab", 1, ["pane:0", "pane:1", "sidebar", "pane:0"]],
    ["shift-tab", -1, ["pane:0", "sidebar", "pane:1", "pane:0"]],
  ] as const)(
    "%s cycles the sidebar and the active workspace's panes",
    (_, step, expected) => {
      let state = splitFocused(openTask(initialLayout(), "a"), "row");
      state = focusPane(state, paneIds(activeWorkspace(state).root)[0]);
      const seen: string[] = [];
      for (const _ of expected) {
        const { root, focusedPaneId } = activeWorkspace(state);
        seen.push(
          state.focus === "sidebar"
            ? "sidebar"
            : `pane:${paneIds(root).indexOf(focusedPaneId)}`,
        );
        state = cycleFocus(state, step);
      }
      expect(seen).toEqual(expected);
    },
  );

  it("remembers the title of each opened task, including in the saved layout", () => {
    const dir = mkdtempSync(join(tmpdir(), "tui-layout-"));
    const path = join(dir, "layout.json");
    let state = openTask(initialLayout(), "a", "Fix the flaky test");
    state = assignTask(
      splitFocused(state, "row"),
      paneIds(activeWorkspace(state).root)[0],
      "a",
      "Renamed",
    );
    saveLayout(state, path);

    expect(activeWorkspace(loadLayout(path)).root).toMatchObject({
      children: [{ taskId: "a", title: "Renamed" }, { taskId: null }],
    });
  });

  it("drops leftover single-pane views from a saved layout, keeping splits and one main view", () => {
    const dir = mkdtempSync(join(tmpdir(), "tui-layout-"));
    const path = join(dir, "layout.json");
    const single = (id: string) => ({
      id,
      root: { kind: "pane", id: `p-${id}`, taskId: id },
      focusedPaneId: `p-${id}`,
    });
    const split = {
      id: "s",
      root: {
        kind: "split",
        direction: "row",
        children: [
          { kind: "pane", id: "p-s1", taskId: "x" },
          { kind: "pane", id: "p-s2", taskId: null },
        ],
      },
      focusedPaneId: "p-s1",
    };
    writeFileSync(
      path,
      JSON.stringify({
        workspaces: [single("a"), split, single("b"), single("c")],
        activeWorkspaceId: "b",
        focus: "pane",
      }),
    );

    const state = loadLayout(path);

    expect(state.workspaces.map((w) => w.id)).toEqual(["s", "b"]);
    expect(state.activeWorkspaceId).toBe("b");
  });

  describe("optimizeWorkspace", () => {
    // The shape of a tree, with each pane named by its task.
    const shape = (node: LayoutNode): unknown =>
      node.kind === "pane"
        ? node.taskId
        : { [node.direction]: node.children.map(shape) };
    // Splits the focused pane and opens a task in the new one, as Ctrl+\\ and a pick would.
    const split = (
      state: LayoutState,
      direction: "row" | "column",
      taskId: string,
    ): LayoutState => openTask(splitFocused(state, direction), taskId);
    const splits = (moves: ["row" | "column", string][]): LayoutState =>
      moves.reduce(
        (state, [direction, taskId]) => split(state, direction, taskId),
        openTask(initialLayout(), "a"),
      );

    it.each([
      ["two stacked panes", [["column", "b"]], { row: ["a", "b"] }],
      [
        "three panes in a row",
        [
          ["row", "b"],
          ["row", "c"],
        ],
        { column: [{ row: ["a", "b"] }, "c"] },
      ],
      [
        "five nested panes",
        [
          ["row", "b"],
          ["row", "c"],
          ["column", "d"],
          ["row", "e"],
        ],
        { column: [{ row: ["a", "b", "c"] }, { row: ["d", "e"] }] },
      ],
      [
        "seven panes",
        ["b", "c", "d", "e", "f", "g"].map((id) => ["row", id]),
        {
          column: [
            { row: ["a", "b", "c"] },
            { row: ["d", "e"] },
            { row: ["f", "g"] },
          ],
        },
      ],
    ] as [string, ["row" | "column", string][], unknown][])(
      "lays out %s in an even grid, keeping the focused pane",
      (_, moves, even) => {
        const state = splits(moves);
        const workspace = activeWorkspace(state);
        const optimized = optimizeWorkspace(state, workspace.id);
        expect(optimized && shape(activeWorkspace(optimized).root)).toEqual(
          even,
        );
        expect(optimized && activeWorkspace(optimized).focusedPaneId).toBe(
          workspace.focusedPaneId,
        );
      },
    );

    it("leaves a grid that is already even alone", () => {
      const state = splits([
        ["row", "b"],
        ["column", "c"],
      ]);
      const optimized = optimizeWorkspace(state, activeWorkspace(state).id);
      expect(optimized).not.toBeNull();
      if (!optimized) return;
      expect(
        optimizeWorkspace(optimized, activeWorkspace(optimized).id),
      ).toBeNull();
    });
  });

  it("expands a split pane's task into the main view and keeps the split", () => {
    const state = openTask(
      splitFocused(openTask(initialLayout(), "a"), "row"),
      "b",
    );
    const workspace = activeWorkspace(state);
    const expanded = expandPane(state, workspace.focusedPaneId);

    expect(activeWorkspace(expanded).root).toMatchObject({
      kind: "pane",
      taskId: "b",
    });
    expect(expanded.workspaces).toContainEqual(workspace);
  });

  it("restores a saved layout and falls back to a fresh one when the file is unreadable", () => {
    const dir = mkdtempSync(join(tmpdir(), "tui-layout-"));
    const path = join(dir, "layout.json");
    const state = splitFocused(openTask(initialLayout(), "a"), "column");
    saveLayout(state, path);
    expect(loadLayout(path)).toEqual(state);

    writeFileSync(path, "{not json");
    expect(loadLayout(path).workspaces).toHaveLength(1);
  });

  it("gives the shared layout to the first account without its own, once", () => {
    const dir = mkdtempSync(join(tmpdir(), "tui-layout-"));
    const shared = join(dir, "layout.json");
    const [first, second] = ["a", "b"].map((id) =>
      join(dir, `layout.${id}.json`),
    );
    const state = splitFocused(openTask(initialLayout(), "a"), "column");
    saveLayout(state, shared);

    adoptSharedLayout(first, shared);
    adoptSharedLayout(second, shared);

    expect(loadLayout(first)).toEqual(state);
    expect(existsSync(shared)).toBe(false);
    expect(existsSync(second)).toBe(false);
  });

  it.each([
    ["even rows", 23, 2, [11, 12]],
    ["odd rows", 24, 2, [12, 12]],
    ["three columns", 100, 3, [33, 34, 33]],
  ])(
    "splits %s into whole cells, each divider taking one",
    (_, total, count, sizes) => {
      const cells = splitSizes(total, count);
      expect(cells).toEqual(sizes);
      expect(cells.reduce((sum, size) => sum + size, 0)).toBe(total);
    },
  );
});
