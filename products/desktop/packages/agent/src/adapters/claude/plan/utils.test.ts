import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { isSubagentPlanFilePath } from "./utils";

describe("isSubagentPlanFilePath", () => {
  it.each([
    ["calm-roaming-inlet-agent-ae27af0da6318b9d6.md", true],
    ["calm-roaming-inlet.md", false],
    // Hex-looking words are why the agent-id match requires length.
    ["rename-the-agent-decade.md", false],
    ["agent-notes.md", false],
  ])("treats %s as a subagent plan: %s", (basename, expected) => {
    expect(
      isSubagentPlanFilePath(path.join("/home/u/.claude/plans", basename)),
    ).toBe(expected);
  });
});
