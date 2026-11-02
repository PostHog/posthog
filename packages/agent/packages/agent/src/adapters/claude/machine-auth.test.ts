import * as os from "node:os";
import * as path from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  applyMachineClaudeAuth,
  keepUserClaudeConfigDir,
} from "./machine-auth";

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

  it("keeps the user's dir for every copy of this module once asked", () => {
    vi.stubEnv("POSTHOG_CLAUDE_USER_CONFIG_DIR", "");
    keepUserClaudeConfigDir();
    const env: Record<string, string | undefined> = {};
    applyMachineClaudeAuth(env, {});
    expect(env).toEqual({});
  });

  afterEach(() => vi.unstubAllEnvs());
});
