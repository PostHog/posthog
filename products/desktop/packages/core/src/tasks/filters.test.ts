import { describe, expect, it } from "vitest";
import {
  type ActiveFilters,
  addFilter,
  getDefaultOperator,
  toggleFilter,
  toggleFilterOperator,
  toggleOperator,
  updateFilter,
} from "./filters";

describe("getDefaultOperator", () => {
  it("returns after for created_at", () => {
    expect(getDefaultOperator("created_at")).toBe("after");
  });

  it("returns is for other categories", () => {
    expect(getDefaultOperator("status")).toBe("is");
    expect(getDefaultOperator("repository")).toBe("is");
  });
});

describe("toggleOperator", () => {
  it("flips before/after for created_at", () => {
    expect(toggleOperator("created_at", "before")).toBe("after");
    expect(toggleOperator("created_at", "after")).toBe("before");
  });

  it("flips is/is_not for other categories", () => {
    expect(toggleOperator("status", "is")).toBe("is_not");
    expect(toggleOperator("status", "is_not")).toBe("is");
  });
});

describe("toggleFilter", () => {
  it("adds a new filter with the default operator", () => {
    const next = toggleFilter({}, "status", "queued");
    expect(next.status).toEqual([{ value: "queued", operator: "is" }]);
  });

  it("removes an existing filter and drops the empty category", () => {
    const prev: ActiveFilters = {
      status: [{ value: "queued", operator: "is" }],
    };
    const next = toggleFilter(prev, "status", "queued");
    expect(next.status).toBeUndefined();
  });

  it("keeps remaining filters when removing one of several", () => {
    const prev: ActiveFilters = {
      status: [
        { value: "queued", operator: "is" },
        { value: "failed", operator: "is" },
      ],
    };
    const next = toggleFilter(prev, "status", "queued");
    expect(next.status).toEqual([{ value: "failed", operator: "is" }]);
  });
});

describe("addFilter", () => {
  it("appends a filter without dedup", () => {
    const prev: ActiveFilters = {
      status: [{ value: "queued", operator: "is" }],
    };
    const next = addFilter(prev, "status", "failed");
    expect(next.status).toHaveLength(2);
  });
});

describe("updateFilter", () => {
  it("replaces the matching value", () => {
    const prev: ActiveFilters = {
      repository: [{ value: "old", operator: "is" }],
    };
    const next = updateFilter(prev, "repository", "old", "new");
    expect(next.repository).toEqual([{ value: "new", operator: "is" }]);
  });

  it("returns unchanged when value is missing", () => {
    const prev: ActiveFilters = {
      repository: [{ value: "old", operator: "is" }],
    };
    const next = updateFilter(prev, "repository", "missing", "new");
    expect(next).toBe(prev);
  });
});

describe("toggleFilterOperator", () => {
  it("flips the operator of the matching value", () => {
    const prev: ActiveFilters = {
      status: [{ value: "queued", operator: "is" }],
    };
    const next = toggleFilterOperator(prev, "status", "queued");
    expect(next.status).toEqual([{ value: "queued", operator: "is_not" }]);
  });

  it("returns unchanged when value is missing", () => {
    const prev: ActiveFilters = {
      status: [{ value: "queued", operator: "is" }],
    };
    const next = toggleFilterOperator(prev, "status", "missing");
    expect(next).toBe(prev);
  });
});
