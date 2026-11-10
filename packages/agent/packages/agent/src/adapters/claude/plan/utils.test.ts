import * as path from "node:path";
import type { ExitPlanModeInput } from "@anthropic-ai/claude-agent-sdk/sdk-tools.js";
import { describe, expect, it } from "vitest";
import { isSubagentPlanFilePath } from "./utils";

type Assert<T extends true> = T;
type _NoPlanOnExitPlanModeInput = Assert<
  ExitPlanModeInput extends { plan: string } ? false : true
>;

describe("isSubagentPlanFilePath", () => {
  it.each([
    ["calm-roaming-inlet-agent-ae27af0da6318b9d6.md", true],
    ["calm-roaming-inlet.md", false],
    ["rename-the-agent-decade.md", false],
    ["agent-notes.md", false],
  ])("treats %s as a subagent plan: %s", (basename, expected) => {
    expect(
      isSubagentPlanFilePath(path.join("/home/u/.claude/plans", basename)),
    ).toBe(expected);
  });
});
