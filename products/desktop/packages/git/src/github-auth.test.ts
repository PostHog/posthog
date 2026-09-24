import { describe, expect, it } from "vitest";
import {
  appendGitConfigEnv,
  GITHUB_AUTH_CONFIG_KEY,
  isGitAuthFailure,
  withGithubAuth,
  withNonInteractiveGit,
} from "./github-auth";

describe("github-auth", () => {
  it("appends git config pairs after the ones already in the environment", () => {
    const env = appendGitConfigEnv(
      {
        GIT_CONFIG_COUNT: "1",
        GIT_CONFIG_KEY_0: "core.pager",
        GIT_CONFIG_VALUE_0: "cat",
      },
      [["http.extraHeader", "AUTHORIZATION: basic abc"]],
    );

    expect(env).toMatchObject({
      GIT_CONFIG_COUNT: "2",
      GIT_CONFIG_KEY_0: "core.pager",
      GIT_CONFIG_VALUE_0: "cat",
      GIT_CONFIG_KEY_1: "http.extraHeader",
      GIT_CONFIG_VALUE_1: "AUTHORIZATION: basic abc",
    });
  });

  it("scopes the auth header to github.com and leaves the env alone without a token", () => {
    const authed = withGithubAuth({}, "ghs_token");
    expect(authed.GIT_CONFIG_KEY_0).toBe(GITHUB_AUTH_CONFIG_KEY);
    expect(authed.GIT_CONFIG_VALUE_0).toBe(
      `AUTHORIZATION: basic ${Buffer.from("x-access-token:ghs_token").toString("base64")}`,
    );

    expect(withGithubAuth({ PATH: "/bin" }, undefined)).toEqual({
      PATH: "/bin",
    });
  });

  // An inherited GIT_ASKPASS still opens a prompt while GIT_TERMINAL_PROMPT is 0,
  // so both have to be set. The ssh command is left to the sandbox image, which
  // has no user core.sshCommand to override.
  it("closes both prompt routes and leaves the ssh command alone", () => {
    expect(withNonInteractiveGit({ PATH: "/bin" })).toEqual({
      PATH: "/bin",
      GIT_TERMINAL_PROMPT: "0",
      GIT_ASKPASS: "",
    });
  });

  it.each([
    ["fatal: could not read Username for 'https://github.com'", true],
    ["fatal: Authentication failed for 'https://github.com/a/b'", true],
    ["git@github.com: Permission denied (publickey).", true],
    // The server's identity failed verification, not the credential.
    ["Host key verification failed.", false],
    ["remote: Repository not found.", true],
    // A transient network failure retries; reporting it as a credential problem would
    // send the user to reconnect GitHub for nothing.
    ["fatal: unable to access: Could not resolve host: github.com", false],
    ["error: RPC failed; curl 92", false],
    ["", false],
  ])("classifies %j as an auth failure: %s", (output, expected) => {
    expect(isGitAuthFailure(output)).toBe(expected);
  });
});
