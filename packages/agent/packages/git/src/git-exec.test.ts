import { describe, expect, it, vi } from "vitest";
import {
  execGitWithRetry,
  type GitExecResult,
  isTransientGitFailure,
} from "./git-exec";

function result(partial: Partial<GitExecResult>): GitExecResult {
  return { stdout: "", stderr: "", exitCode: 1, ...partial };
}

describe("git-exec retry", () => {
  describe("isTransientGitFailure", () => {
    it.each([
      {
        name: "HTTP 502",
        res: result({
          stderr:
            "fatal: unable to access: The requested URL returned error: 502",
        }),
        expected: true,
      },
      {
        name: "timeout",
        res: result({ error: "git timed out after 600000ms" }),
        expected: true,
      },
      {
        name: "ECONNRESET",
        res: result({ error: "read ECONNRESET" }),
        expected: true,
      },
      {
        name: "unresolvable host",
        res: result({
          stderr: "fatal: unable to access: Could not resolve host: github.com",
        }),
        expected: true,
      },
      {
        name: "interrupted transfer",
        res: result({ stderr: "fetch-pack: unexpected disconnect, early EOF" }),
        expected: true,
      },
      {
        name: "success",
        res: result({ exitCode: 0, stderr: "early EOF" }),
        expected: false,
      },
      {
        name: "auth failure",
        res: result({
          stderr: "fatal: Authentication failed for 'https://github.com/x.git'",
        }),
        expected: false,
      },
      {
        name: "missing remote ref",
        res: result({ stderr: "fatal: couldn't find remote ref missing" }),
        expected: false,
      },
    ])("$name -> $expected", ({ res, expected }) => {
      expect(isTransientGitFailure(res)).toBe(expected);
    });
  });

  describe("execGitWithRetry", () => {
    it("retries transient failures then succeeds", async () => {
      const exec = vi
        .fn()
        .mockResolvedValueOnce(result({ stderr: "early EOF" }))
        .mockResolvedValueOnce(result({ stdout: "ok", exitCode: 0 }));
      const res = await execGitWithRetry(["fetch"], {}, { backoffMs: 0 }, exec);
      expect(res.exitCode).toBe(0);
      expect(exec).toHaveBeenCalledTimes(2);
    });

    it("stops after maxAttempts on persistent transient failure", async () => {
      const exec = vi.fn().mockResolvedValue(result({ stderr: "early EOF" }));
      const res = await execGitWithRetry(
        ["fetch"],
        {},
        { maxAttempts: 3, backoffMs: 0 },
        exec,
      );
      expect(res.exitCode).toBe(1);
      expect(exec).toHaveBeenCalledTimes(3);
    });

    it("does not retry deterministic failures", async () => {
      const exec = vi
        .fn()
        .mockResolvedValue(result({ stderr: "fatal: Authentication failed" }));
      const res = await execGitWithRetry(["fetch"], {}, { backoffMs: 0 }, exec);
      expect(res.exitCode).toBe(1);
      expect(exec).toHaveBeenCalledTimes(1);
    });
  });
});
