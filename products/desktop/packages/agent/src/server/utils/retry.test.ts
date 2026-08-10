import { describe, expect, it, vi } from "vitest";
import { retry } from "./retry";

describe("retry", () => {
  it("returns result on first success", async () => {
    const fn = vi.fn().mockResolvedValue("success");

    const result = await retry(fn);

    expect(result).toBe("success");
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("retries on transient error and succeeds", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("network error"))
      .mockResolvedValue("success");

    const result = await retry(fn, { baseDelayMs: 1 });

    expect(result).toBe("success");
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("throws after max attempts", async () => {
    const fn = vi.fn().mockRejectedValue(new Error("network error"));

    await expect(retry(fn, { maxAttempts: 3, baseDelayMs: 1 })).rejects.toThrow(
      "network error",
    );

    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("does not retry on non-transient error", async () => {
    const fn = vi.fn().mockRejectedValue(new Error("validation failed"));

    await expect(retry(fn, { baseDelayMs: 1 })).rejects.toThrow(
      "validation failed",
    );

    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("respects custom shouldRetry", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("custom error"))
      .mockResolvedValue("success");

    const result = await retry(fn, {
      baseDelayMs: 1,
      shouldRetry: (err) => err.message === "custom error",
    });

    expect(result).toBe("success");
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("uses exponential backoff", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("timeout"))
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValue("success");

    const start = Date.now();
    await retry(fn, { baseDelayMs: 50, maxDelayMs: 200 });
    const elapsed = Date.now() - start;

    // First retry: 50ms, second retry: 100ms = 150ms minimum
    expect(elapsed).toBeGreaterThanOrEqual(100);
  });

  it("caps delay at maxDelayMs", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("timeout"))
      .mockRejectedValueOnce(new Error("timeout"))
      .mockRejectedValueOnce(new Error("timeout"))
      .mockResolvedValue("success");

    const start = Date.now();
    await retry(fn, { maxAttempts: 4, baseDelayMs: 100, maxDelayMs: 150 });
    const elapsed = Date.now() - start;

    // With cap: 100 + 150 + 150 = 400ms max (not 100 + 200 + 400 = 700ms)
    expect(elapsed).toBeLessThan(600);
  });

  it("retries on 429 rate limit", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("429 Too Many Requests"))
      .mockResolvedValue("success");

    const result = await retry(fn, { baseDelayMs: 1 });

    expect(result).toBe("success");
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("retries on 502/503 server errors", async () => {
    const fn = vi
      .fn()
      .mockRejectedValueOnce(new Error("502 Bad Gateway"))
      .mockRejectedValueOnce(new Error("503 Service Unavailable"))
      .mockResolvedValue("success");

    const result = await retry(fn, { baseDelayMs: 1 });

    expect(result).toBe("success");
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("converts non-Error throws to Error", async () => {
    const fn = vi.fn().mockRejectedValue("string error");

    await expect(retry(fn, { maxAttempts: 1 })).rejects.toThrow("string error");
  });
});
