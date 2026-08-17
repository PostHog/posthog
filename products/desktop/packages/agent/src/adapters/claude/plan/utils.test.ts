import * as path from "node:path";
import type { ExitPlanModeInput } from "@anthropic-ai/claude-agent-sdk/sdk-tools.js";
import { describe, expect, it } from "vitest";
import { isSubagentPlanFilePath } from "./utils";

/**
 * Reading the plan from its file rests on `ExitPlanMode` carrying no plan of its own.
 * The CLI is an unpinned binary, so an SDK bump can change that under us while every
 * runtime test keeps passing — this fails `tsc` on the bump instead. If the input
 * gains a `plan`, the file stops being the only source and `resolvePlanInput`'s
 * precedence needs revisiting.
 *
 * A live e2e would cover the same ground, but that suite is opt-in and off in CI, so
 * it would not run on the version bump that matters. Whether the CLI still assigns a
 * plan file at all stays untested by design: that is black-box behavior, and the
 * mitigation is degrading to a recoverable denial rather than asserting on it.
 */
type Assert<T extends true> = T;
type _NoPlanOnExitPlanModeInput = Assert<
  ExitPlanModeInput extends { plan: string } ? false : true
>;

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
