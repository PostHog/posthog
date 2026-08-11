import { describe, expect, it, vi } from "vitest";
import { execGhWithRetry, type GhExecResult, isTransientGhFailure } from "./gh";

function result(partial: Partial<GhExecResult>): GhExecResult {
  return { stdout: "", stderr: "", exitCode: 1, ...partial };
}

describe("isTransientGhFailure", () => {
  it.each([
    {
      name: "HTTP 499",
      res: result({ stderr: "gh: HTTP 499" }),
      expected: true,
    },
    {
      name: "HTTP 502",
      res: result({ stderr: "gh: HTTP 502" }),
      expected: true,
    },
    {
      name: "timeout",
      res: result({ error: "gh timed out after 30000ms" }),
      expected: true,
    },
    {
      name: "ECONNRESET",
      res: result({ error: "read ECONNRESET" }),
      expected: true,
    },
    {
      name: "success",
      res: result({ exitCode: 0, stderr: "gh: HTTP 499" }),
      expected: false,
    },
    {
      name: "HTTP 404",
      res: result({ stderr: "gh: HTTP 404" }),
      expected: false,
    },
    {
      name: "HTTP 422 validation",
      res: result({ stderr: "gh: HTTP 422" }),
      expected: false,
    },
  ])("$name -> $expected", ({ res, expected }) => {
    expect(isTransientGhFailure(res)).toBe(expected);
  });
});

describe("execGhWithRetry", () => {
  it("retries transient failures then succeeds", async () => {
    const exec = vi
      .fn()
      .mockResolvedValueOnce(result({ stderr: "gh: HTTP 499" }))
      .mockResolvedValueOnce(result({ stdout: "ok", exitCode: 0 }));
    const res = await execGhWithRetry(["api"], {}, { backoffMs: 0 }, exec);
    expect(res.exitCode).toBe(0);
    expect(exec).toHaveBeenCalledTimes(2);
  });

  it("stops after maxAttempts on persistent transient failure", async () => {
    const exec = vi.fn().mockResolvedValue(result({ stderr: "gh: HTTP 503" }));
    const res = await execGhWithRetry(
      ["api"],
      {},
      { maxAttempts: 3, backoffMs: 0 },
      exec,
    );
    expect(res.exitCode).toBe(1);
    expect(exec).toHaveBeenCalledTimes(3);
  });

  it("does not retry deterministic failures", async () => {
    const exec = vi.fn().mockResolvedValue(result({ stderr: "gh: HTTP 404" }));
    const res = await execGhWithRetry(["api"], {}, { backoffMs: 0 }, exec);
    expect(res.exitCode).toBe(1);
    expect(exec).toHaveBeenCalledTimes(1);
  });
});
