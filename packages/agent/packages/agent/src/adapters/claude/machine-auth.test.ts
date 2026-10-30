import * as os from "node:os";
import * as path from "node:path";
import { describe, expect, it } from "vitest";
import { applyMachineClaudeAuth } from "./machine-auth";

describe("applyMachineClaudeAuth", () => {
  it("pins the default config dir unless told to keep the user's own", () => {
    const pinned: Record<string, string | undefined> = {
      ANTHROPIC_API_KEY: "k",
    };
    applyMachineClaudeAuth(pinned, {});
    expect(pinned).toEqual({
      CLAUDE_CONFIG_DIR: path.join(os.homedir(), ".claude"),
    });

    const kept: Record<string, string | undefined> = { ANTHROPIC_API_KEY: "k" };
    applyMachineClaudeAuth(kept, { keepUserConfigDir: true });
    expect(kept).toEqual({});

    const custom: Record<string, string | undefined> = {
      CLAUDE_CONFIG_DIR: "/x",
    };
    applyMachineClaudeAuth(custom, { keepUserConfigDir: true });
    expect(custom).toEqual({ CLAUDE_CONFIG_DIR: "/x" });
  });
});
