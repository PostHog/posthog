import { describe, expect, it } from "vitest";
import {
  offeredScoutWriteScopes,
  SCOUT_WRITE_SCOPE_ROWS,
  sameScoutWriteScopes,
  scoutWriteScopeLabels,
} from "./scoutWriteScopes";

describe("scoutWriteScopes", () => {
  it("offers a row for every scope the API grants", () => {
    expect(SCOUT_WRITE_SCOPE_ROWS.map((row) => row.scope).sort()).toEqual([
      "alert:write",
      "annotation:write",
      "dashboard:write",
      "insight:write",
      "llm_skill:write",
      "warehouse_table:write",
      "warehouse_view:write",
    ]);
  });

  it.each([
    ["no grant", [], []],
    ["one grant", ["llm_skill:write"], ["Skills"]],
    // A scope the allowlist dropped has no switch, so naming it would promise a control the
    // person cannot reach.
    ["a scope the picker no longer offers", ["cohort:write"], []],
  ])("labels %s", (_name, scopes, labels) => {
    expect(scoutWriteScopeLabels(scopes)).toEqual(labels);
  });

  it("drops a stale scope from the scopes it offers", () => {
    // Sending a stale scope back would get the whole update rejected, leaving no way to clear it.
    expect(
      offeredScoutWriteScopes(["cohort:write", "warehouse_table:write"]),
    ).toEqual(["warehouse_table:write"]);
  });

  it.each([
    [
      "order only",
      ["insight:write", "alert:write"],
      ["alert:write", "insight:write"],
      true,
    ],
    ["a cleared grant", ["insight:write"], [], false],
  ])("compares grants by %s", (_name, a, b, same) => {
    expect(sameScoutWriteScopes(a, b)).toBe(same);
  });
});
