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

  it("opens a task that is not open yet in a new workspace", () => {
    const state = openTask(openTask(initialLayout(), "a"), "b");
    expect(state.workspaces).toHaveLength(2);
    expect(state.activeWorkspaceId).toBe(state.workspaces[1].id);
    expect(focusedTask(state)).toBe("b");
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

  it("closing a workspace's last pane moves to another workspace, and the very last pane quits", () => {
    const two = openTask(openTask(initialLayout(), "a"), "b");
    const one = closeFocused(two) as LayoutState;
    expect(one.workspaces).toHaveLength(1);
    expect(focusedTask(one)).toBe("a");
    expect(closeFocused(one)).toBe("quit");
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
