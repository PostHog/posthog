import { describe, expect, it } from "vitest";
import { summarizeReadStates } from "./reportReadState";

describe("summarizeReadStates", () => {
  it("counts only a state the server returned as false as unread", () => {
    const states = summarizeReadStates(
      ["read", "unread", "failed"],
      [
        { data: true, isFetchedAfterMount: true },
        { data: false, isFetchedAfterMount: true },
        { data: undefined, isFetchedAfterMount: true },
      ],
    );
    expect([...states.unread]).toEqual(["unread"]);
    expect(states.settled).toBe(true);
  });

  it("is not settled while a cached state waits for the server", () => {
    const states = summarizeReadStates(
      ["a", "b"],
      [
        { data: false, isFetchedAfterMount: false },
        { data: true, isFetchedAfterMount: true },
      ],
    );
    expect(states.settled).toBe(false);
    expect([...states.unread]).toEqual(["a"]);
  });
});
