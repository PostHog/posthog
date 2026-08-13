import { describe, expect, it } from "vitest";
import { pendingServerArchiveIds } from "./serverArchiveSync";

const tasks = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }];

describe("pendingServerArchiveIds", () => {
  it.each([
    {
      name: "picks the archived tasks the server still lists",
      archived: ["b", "d"],
      handled: [],
      limit: 25,
      expected: ["b", "d"],
    },
    {
      name: "skips ids a pass has already sent",
      archived: ["b", "d"],
      handled: ["b"],
      limit: 25,
      expected: ["d"],
    },
    {
      name: "stops at the limit",
      archived: ["a", "b", "c"],
      handled: [],
      limit: 2,
      expected: ["a", "b"],
    },
    {
      name: "has nothing to do when nothing is archived",
      archived: [],
      handled: [],
      limit: 25,
      expected: [],
    },
  ])("$name", ({ archived, handled, limit, expected }) => {
    expect(
      pendingServerArchiveIds(
        tasks,
        new Set(archived),
        new Set(handled),
        limit,
      ),
    ).toEqual(expected);
  });
});
