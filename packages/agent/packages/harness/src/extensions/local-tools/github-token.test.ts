import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  readGithubTokenFromSandboxEnvFile,
  resolveGithubToken,
} from "./github-token";

function writeEnvFile(contents: string): string {
  const dir = mkdtempSync(join(tmpdir(), "agent-env-"));
  const path = join(dir, "agent-env");
  writeFileSync(path, contents);
  return path;
}

describe("github-token", () => {
  describe("readGithubTokenFromSandboxEnvFile", () => {
    it.each([
      {
        name: "GH_TOKEN",
        contents: "PATH=/usr/bin\0GH_TOKEN=ghs_fresh123\0HOME=/root\0",
        expected: "ghs_fresh123",
      },
      {
        name: "GITHUB_TOKEN when GH_TOKEN is absent",
        contents: "GITHUB_TOKEN=ghu_user456\0PATH=/usr/bin\0",
        expected: "ghu_user456",
      },
    ])(
      "reads $name from the NUL-delimited env file",
      ({ contents, expected }) => {
        expect(readGithubTokenFromSandboxEnvFile(writeEnvFile(contents))).toBe(
          expected,
        );
      },
    );

    it("reflects an updated file (live read, not cached)", () => {
      const path = writeEnvFile("GH_TOKEN=ghs_old\0");
      expect(readGithubTokenFromSandboxEnvFile(path)).toBe("ghs_old");
      writeFileSync(path, "GH_TOKEN=ghs_new\0");
      expect(readGithubTokenFromSandboxEnvFile(path)).toBe("ghs_new");
    });

    it("returns undefined when the file is missing", () => {
      expect(
        readGithubTokenFromSandboxEnvFile("/nonexistent/agent-env"),
      ).toBeUndefined();
    });

    it("fails closed ('') when the file exists but is unreadable (not ENOENT)", () => {
      // A directory path triggers EISDIR, standing in for a transiently unreadable
      // managed file during a transition — must not resurrect the process env.
      const dir = mkdtempSync(join(tmpdir(), "agent-env-dir-"));
      expect(readGithubTokenFromSandboxEnvFile(dir)).toBe("");
    });

    it("ignores an empty token value", () => {
      const path = writeEnvFile("GH_TOKEN=\0GITHUB_TOKEN=ghs_real\0");
      expect(readGithubTokenFromSandboxEnvFile(path)).toBe("ghs_real");
    });

    it("returns '' (explicit logout) when every token var is present but empty", () => {
      const path = writeEnvFile("PATH=/usr/bin\0GH_TOKEN=\0GITHUB_TOKEN=\0");
      expect(readGithubTokenFromSandboxEnvFile(path)).toBe("");
    });

    it("returns '' (logout) when the managed file is truncated to zero bytes", () => {
      // The backend logs the sandbox out by writing an empty file, not emptied vars.
      expect(readGithubTokenFromSandboxEnvFile(writeEnvFile(""))).toBe("");
      expect(readGithubTokenFromSandboxEnvFile(writeEnvFile("   \n"))).toBe("");
    });

    it("returns undefined when the file carries no token var at all", () => {
      const path = writeEnvFile("PATH=/usr/bin\0HOME=/root\0");
      expect(readGithubTokenFromSandboxEnvFile(path)).toBeUndefined();
    });
  });

  describe("resolveGithubToken", () => {
    afterEach(() => {
      vi.unstubAllEnvs();
    });

    it("prefers the sandbox env file over the process env", () => {
      vi.stubEnv("GH_TOKEN", "ghs_fromprocess");
      const path = writeEnvFile("GH_TOKEN=ghs_fromfile\0");
      expect(resolveGithubToken(path)).toBe("ghs_fromfile");
    });

    it("falls back to the process env when the sandbox file is absent", () => {
      vi.stubEnv("GH_TOKEN", "ghs_fromprocess");
      expect(resolveGithubToken("/nonexistent/agent-env")).toBe(
        "ghs_fromprocess",
      );
    });

    it("does not resurrect the process-env token after a logout (emptied file)", () => {
      // The backend logs the sandbox out by emptying the token vars in the file.
      // The frozen launch-time process env still holds the previous actor's
      // token; resolving must NOT fall back to it.
      vi.stubEnv("GH_TOKEN", "ghs_previous_actor");
      const path = writeEnvFile("GH_TOKEN=\0GITHUB_TOKEN=\0");
      expect(resolveGithubToken(path)).toBe("");
    });

    it("does not resurrect the process-env token when the file is zero bytes (logout)", () => {
      // The backend's actual logout truncates the file to zero bytes; resolving
      // must treat that as logout, not fall back to the frozen process env.
      vi.stubEnv("GH_TOKEN", "ghs_previous_actor");
      expect(resolveGithubToken(writeEnvFile(""))).toBe("");
    });

    it("falls back to the process env when the file carries no token var", () => {
      vi.stubEnv("GH_TOKEN", "ghs_fromprocess");
      const path = writeEnvFile("PATH=/usr/bin\0");
      expect(resolveGithubToken(path)).toBe("ghs_fromprocess");
    });

    it("does not fall back to the process env when the file is unreadable", () => {
      // Present-but-unreadable (EISDIR here) is a managed sandbox mid-transition,
      // not an absent file, so it must not resurrect the frozen process token.
      vi.stubEnv("GH_TOKEN", "ghs_previous_actor");
      const dir = mkdtempSync(join(tmpdir(), "agent-env-dir-"));
      expect(resolveGithubToken(dir)).toBe("");
    });
  });
});
