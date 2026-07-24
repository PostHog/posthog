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

    it("ignores an empty token value", () => {
      const path = writeEnvFile("GH_TOKEN=\0GITHUB_TOKEN=ghs_real\0");
      expect(readGithubTokenFromSandboxEnvFile(path)).toBe("ghs_real");
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
  });
});
