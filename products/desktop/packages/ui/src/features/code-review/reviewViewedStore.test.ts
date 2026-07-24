import { beforeEach, describe, expect, it } from "vitest";
import { useReviewViewedStore } from "./reviewViewedStore";

const { setViewed, clearTasks } = useReviewViewedStore.getState();
const viewed = () => useReviewViewedStore.getState().viewed;

describe("reviewViewedStore", () => {
  beforeEach(() => useReviewViewedStore.setState({ viewed: {} }));

  it("marks a file read at its signature", () => {
    setViewed("t1", "a.ts", "sig1");
    expect(viewed().t1).toEqual({ "a.ts": "sig1" });
  });

  it("unmarks a file and drops the task once it has no read files", () => {
    setViewed("t1", "a.ts", "sig1");
    setViewed("t1", "a.ts", null);
    expect(viewed().t1).toBeUndefined();
  });

  it("keeps other read files when unmarking one", () => {
    setViewed("t1", "a.ts", "s");
    setViewed("t1", "b.ts", "s");
    setViewed("t1", "a.ts", null);
    expect(viewed().t1).toEqual({ "b.ts": "s" });
  });

  it("clearTasks removes the given tasks only", () => {
    setViewed("t1", "a", "s");
    setViewed("t2", "a", "s");
    setViewed("t3", "a", "s");
    clearTasks(["t1", "t3"]);
    expect(Object.keys(viewed())).toEqual(["t2"]);
  });

  it("clearTasks is a no-op (same reference) when nothing matches", () => {
    setViewed("t1", "a", "s");
    const before = viewed();
    clearTasks(["unknown"]);
    expect(viewed()).toBe(before);
  });
});
