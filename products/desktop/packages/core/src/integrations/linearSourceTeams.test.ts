import { describe, expect, it } from "vitest";
import {
  buildLinearTeamIdsConfig,
  linearTeamIdsFromConfig,
  linearTeamsSummary,
} from "./linearSourceTeams";

describe("linearSourceTeams", () => {
  it.each([
    ["missing config", undefined, []],
    ["missing key", {}, []],
    ["empty list", { linear_team_ids: [] }, []],
    ["a non-list value", { linear_team_ids: "team-1" }, []],
    [
      "non-string entries",
      { linear_team_ids: ["team-1", 7, "", null] },
      ["team-1"],
    ],
  ])("reads %s as %j", (_name, config, expected) => {
    expect(linearTeamIdsFromConfig(config as Record<string, unknown>)).toEqual(
      expected,
    );
  });

  it("keeps the rest of the config when the team list changes", () => {
    expect(
      buildLinearTeamIdsConfig(
        { steering: "Skip chores", linear_team_ids: ["team-1"] },
        ["team-2"],
      ),
    ).toEqual({ steering: "Skip chores", linear_team_ids: ["team-2"] });
  });

  it.each([
    [undefined, "All teams"],
    [{ linear_team_ids: [] }, "All teams"],
    [{ linear_team_ids: ["team-1"] }, "1 team"],
    [{ linear_team_ids: ["team-1", "team-2"] }, "2 teams"],
  ])("summarizes %j as %s", (config, expected) => {
    expect(linearTeamsSummary(config as Record<string, unknown>)).toBe(
      expected,
    );
  });
});
