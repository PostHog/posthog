import { describe, expect, it, vi } from "vitest";
import { PreviewRevisionChecker } from "./previewRevision";

const INPUT = {
  backendOrigin: "https://preview.example.com",
  expectedCommitSha: "1".repeat(40),
  metadataPath: "/static/desktop-preview/deployment.json",
  timeoutMs: 5000,
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

describe("PreviewRevisionChecker", () => {
  const checker = new PreviewRevisionChecker();

  it("matches when the served SHA equals the built SHA", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        schemaVersion: 1,
        prNumber: 123,
        commitSha: "1".repeat(40),
        deploymentGeneration: 4,
      }),
    );
    const verdict = await checker.check({
      ...INPUT,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(verdict).toEqual({ status: "match" });
  });

  it("reports stale when a push replaced the backend", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        schemaVersion: 1,
        prNumber: 123,
        commitSha: "2".repeat(40),
        deploymentGeneration: 5,
      }),
    );
    const verdict = await checker.check({
      ...INPUT,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(verdict).toEqual({
      status: "stale",
      servedCommitSha: "2".repeat(40),
    });
  });

  it("reports waking on the hibernation 503", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}, 503));
    const verdict = await checker.check({
      ...INPUT,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(verdict).toEqual({ status: "waking" });
  });

  it("fails closed when the route serves the SPA instead of JSON", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse("<!doctype html><html></html>"));
    const verdict = await checker.check({
      ...INPUT,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(verdict.status).toBe("unknown");
  });

  it("fails closed on a JSON body with the wrong shape", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(jsonResponse({ hello: "world" }));
    const verdict = await checker.check({
      ...INPUT,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(verdict.status).toBe("unknown");
  });

  it("fails closed on a truncated commit SHA", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        schemaVersion: 1,
        prNumber: 123,
        commitSha: "abc123",
        deploymentGeneration: 1,
      }),
    );
    const verdict = await checker.check({
      ...INPUT,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(verdict.status).toBe("unknown");
  });

  it("fails closed on a network error", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("Failed to fetch"));
    const verdict = await checker.check({
      ...INPUT,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(verdict.status).toBe("unknown");
  });

  it("requests with no-store so a stale cache cannot mask a replacement", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({
        schemaVersion: 1,
        prNumber: 123,
        commitSha: "1".repeat(40),
        deploymentGeneration: 1,
      }),
    );
    await checker.check({
      ...INPUT,
      fetchImpl: fetchImpl as unknown as typeof fetch,
    });
    expect(fetchImpl).toHaveBeenCalledWith(
      "https://preview.example.com/static/desktop-preview/deployment.json",
      expect.objectContaining({ cache: "no-store" }),
    );
  });
});
