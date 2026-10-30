import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  activeWorkspace,
  assignTask,
  closeFocused,
  cycleFocus,
  focusPane,
  initialLayout,
  type LayoutState,
  loadLayout,
  newChat,
  openTask,
  paneIds,
  saveLayout,
  splitFocused,
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

  it("restores a saved layout and falls back to a fresh one when the file is unreadable", () => {
    const dir = mkdtempSync(join(tmpdir(), "tui-layout-"));
    const path = join(dir, "layout.json");
    const state = splitFocused(openTask(initialLayout(), "a"), "column");
    saveLayout(state, path);
    expect(loadLayout(path)).toEqual(state);

    writeFileSync(path, "{not json");
    expect(loadLayout(path).workspaces).toHaveLength(1);
  });
});
