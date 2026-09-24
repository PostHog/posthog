import { afterEach, describe, expect, it } from "vitest";
import { GITHUB_AUTH_CONFIG_KEY } from "./github-auth";
import { getCleanEnv } from "./operation-manager";

describe("getCleanEnv", () => {
  const original = { ...process.env };

  afterEach(() => {
    process.env = { ...original };
  });

  it("disables the terminal prompt so a missing credential fails instead of hanging", () => {
    delete process.env.GH_TOKEN;
    delete process.env.GITHUB_TOKEN;

    const env = getCleanEnv();

    expect(env.GIT_TERMINAL_PROMPT).toBe("0");
    expect(env.GIT_CONFIG_COUNT).toBeUndefined();
  });

  it("carries the GitHub token into every git subprocess, not just clones", () => {
    process.env.GH_TOKEN = "ghs_token";

    const env = getCleanEnv();

    expect(env.GIT_CONFIG_KEY_0).toBe(GITHUB_AUTH_CONFIG_KEY);
    expect(env.GIT_CONFIG_VALUE_0).toContain("AUTHORIZATION: basic ");
  });
});
