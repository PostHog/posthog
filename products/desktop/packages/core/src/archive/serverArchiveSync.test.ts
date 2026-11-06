import { describe, expect, it } from "vitest";
import { pendingServerArchiveIds } from "./serverArchiveSync";

describe("pendingServerArchiveIds", () => {
  it.each([
    {
      name: "picks every archived task not yet mirrored",
      archived: ["a", "b", "c"],
      skip: [],
      expected: ["a", "b", "c"],
    },
    {
      name: "skips ids already synced or already tried this run",
      archived: ["a", "b", "c"],
      skip: ["a", "c"],
      expected: ["b"],
    },
    {
      name: "has nothing to do when the archive is fully mirrored",
      archived: ["a", "b"],
      skip: ["a", "b"],
      expected: [],
    },
    {
      name: "has nothing to do when nothing is archived",
      archived: [],
      skip: ["a"],
      expected: [],
    },
  ])("$name", ({ archived, skip, expected }) => {
    expect(pendingServerArchiveIds(new Set(archived), new Set(skip))).toEqual(
      expected,
    );
  });
});
