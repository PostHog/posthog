import { describe, expect, it } from "vitest";
import {
  CLAUDE_CLI_SUPPORT_DIRS,
  CLAUDE_CLI_SUPPORT_FILES,
  claudeExecutableCandidates,
} from "../../build/native-binary.mjs";

describe("claudeExecutableCandidates", () => {
  it("includes the legacy cli.js fallback after native binary candidates", () => {
    const candidates = claudeExecutableCandidates("/tmp/node_modules");
    expect(candidates.at(-1)).toBe(
      "/tmp/node_modules/@anthropic-ai/claude-agent-sdk/cli.js",
    );
  });
});

describe("Claude CLI support assets", () => {
  it("tracks the files needed by the legacy SDK layout", () => {
    expect(CLAUDE_CLI_SUPPORT_FILES).toEqual([
      "package.json",
      "manifest.json",
      "manifest.zst.json",
      "yoga.wasm",
    ]);
    expect(CLAUDE_CLI_SUPPORT_DIRS).toEqual(["vendor"]);
  });
});
