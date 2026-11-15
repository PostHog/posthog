import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { API_TRANSFER_TIMEOUT_MS, PostHogHttpClient } from "./api-http-client";

const mockFetch = vi.fn();

vi.stubGlobal("fetch", mockFetch);

describe("PostHogHttpClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFetch.mockResolvedValue(new Response());
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses the transfer timeout when the caller provides no signal", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const client = new PostHogHttpClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 1,
    });

    await client.performRequest("/api/test", { method: "GET" });

    expect(timeout).toHaveBeenCalledWith(API_TRANSFER_TIMEOUT_MS);
  });

  it("preserves a caller-provided signal", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const signal = new AbortController().signal;
    const client = new PostHogHttpClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 1,
    });

    await client.performRequest("/api/test", { method: "GET", signal });

    expect(timeout).not.toHaveBeenCalled();
    expect(mockFetch).toHaveBeenCalledWith(
      "https://app.posthog.com/api/test",
      expect.objectContaining({ signal }),
    );
  });
});
