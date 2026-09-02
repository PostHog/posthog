import { describe, expect, it } from "vitest";
import { getNextArchivedTaskPage } from "./useArchivedTaskSummaries";

describe("getNextArchivedTaskPage", () => {
  it("returns the number of requested tasks as the next offset", () => {
    expect(
      getNextArchivedTaskPage(
        [
          { results: [], requested: 50 },
          { results: [], requested: 50 },
        ],
        125,
      ),
    ).toBe(100);
  });

  it("stops after every archived task has been requested", () => {
    expect(
      getNextArchivedTaskPage(
        [
          { results: [], requested: 50 },
          { results: [], requested: 25 },
        ],
        75,
      ),
    ).toBeUndefined();
  });
});
