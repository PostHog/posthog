import type { HookInput } from "@anthropic-ai/claude-agent-sdk";
import { describe, expect, test } from "vitest";
import type { Logger } from "../../../utils/logger";
import { createRtkRewriteHook } from "./rtk-hook";

describe("createRtkRewriteHook", () => {
  const logger = {
    info() {},
    warn() {},
    error() {},
    debug() {},
  } as unknown as Logger;

  const bashInput = (command: string): HookInput =>
    ({
      session_id: "s",
      transcript_path: "/tmp/t",
      cwd: "/tmp",
      hook_event_name: "PreToolUse",
      tool_name: "Bash",
      tool_input: { command },
    }) as unknown as HookInput;

  test("rewrites an eligible Bash command to updatedInput", async () => {
    const hook = createRtkRewriteHook("rtk", logger);
    const result = await hook(bashInput("git status"), "tool-1", {
      signal: new AbortController().signal,
    });
    expect(result).toMatchObject({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        updatedInput: { command: "rtk git status" },
      },
    });
  });

  test("passes ineligible commands through untouched", async () => {
    const hook = createRtkRewriteHook("rtk", logger);
    const result = await hook(bashInput("npm test"), "tool-1", {
      signal: new AbortController().signal,
    });
    expect(result).toEqual({ continue: true });
  });

  test("ignores non-Bash tools", async () => {
    const hook = createRtkRewriteHook("rtk", logger);
    const input = {
      session_id: "s",
      transcript_path: "/tmp/t",
      cwd: "/tmp",
      hook_event_name: "PreToolUse",
      tool_name: "Read",
      tool_input: { file_path: "/x" },
    } as unknown as HookInput;
    const result = await hook(input, "tool-1", {
      signal: new AbortController().signal,
    });
    expect(result).toEqual({ continue: true });
  });
});
