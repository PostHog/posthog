import { describe, expect, it } from "vitest";
import { back, forward, noHistory, spotOf, visited } from "./history";
import {
  activeWorkspace,
  assignTask,
  closeFocused,
  focusPane,
  initialLayout,
  openTask,
  paneIds,
  splitFocused,
} from "./layout";

const stepped = (
  result: ReturnType<typeof back>,
): NonNullable<ReturnType<typeof back>> => {
  if (!result) throw new Error("expected a step");
  return result;
};

describe("history", () => {
  // A split with task a on the left and b on the right, focused on b.
  const split = openTask(
    splitFocused(openTask(initialLayout(), "a"), "row"),
    "b",
  );
  const [left, right] = paneIds(activeWorkspace(split).root);

  it("steps back through the spots visited, and forward again, reopening a chat a pane has since left", () => {
    let layout = focusPane(split, left);
    let history = visited(noHistory, spotOf(layout));
    layout = focusPane(layout, right);
    history = visited(history, spotOf(layout));
    // The right pane moves on to c; back brings b into it again.
    layout = assignTask(layout, right, "c");
    history = visited(history, spotOf(layout));

    ({ history, layout } = stepped(back(history, layout)));
    expect(activeWorkspace(layout).focusedPaneId).toBe(right);
    expect(activeWorkspace(layout).root).toMatchObject({ kind: "split" });
    expect(spotOf(layout)).toMatchObject({ paneId: right, taskId: "b" });

    ({ history, layout } = stepped(back(history, layout)));
    expect(spotOf(layout)).toMatchObject({ paneId: left, taskId: "a" });
    expect(back(history, layout)).toBeNull();

    ({ history, layout } = stepped(forward(history, layout)));
    expect(spotOf(layout)).toMatchObject({ paneId: right, taskId: "b" });
    ({ history, layout } = stepped(forward(history, layout)));
    expect(spotOf(layout)).toMatchObject({ paneId: right, taskId: "c" });
    expect(forward(history, layout)).toBeNull();
  });

  it("records a spot once, and a new spot after going back drops what was ahead", () => {
    let layout = focusPane(split, left);
    let history = visited(noHistory, spotOf(layout));
    history = visited(history, spotOf(layout));
    layout = focusPane(layout, right);
    history = visited(history, spotOf(layout));
    expect(history.back).toHaveLength(1);

    ({ history, layout } = stepped(back(history, layout)));
    expect(history.forward).toHaveLength(1);
    layout = assignTask(layout, left, "d");
    history = visited(history, spotOf(layout));
    expect(history.forward).toHaveLength(0);
    expect(history.back.map((spot) => spot.taskId)).toEqual(["a"]);
  });

  it("skips a spot whose pane has been closed", () => {
    let layout = focusPane(split, left);
    let history = visited(noHistory, spotOf(layout));
    layout = focusPane(layout, right);
    history = visited(history, spotOf(layout));
    const closed = closeFocused(layout);
    layout = closed === "quit" ? layout : closed;
    history = visited(history, spotOf(layout));

    expect(spotOf(stepped(back(history, layout)).layout)).toMatchObject({
      paneId: left,
      taskId: "a",
    });
  });
});
