import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchGatewayModels, fetchModelsList } from "./gateway-models";

describe("gateway model fetch timeout", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  // Both fetches run inside the Promise.all that gates session-init, so a
  // stalled gateway must degrade to "no models" rather than hang.
  it.each([
    { name: "fetchGatewayModels", fn: fetchGatewayModels },
    { name: "fetchModelsList", fn: fetchModelsList },
  ])(
    "$name bounds the request and returns [] when it times out",
    async ({ fn }) => {
      // Reject the way AbortSignal.timeout would once the deadline passes.
      const fetchMock = vi
        .spyOn(globalThis, "fetch")
        .mockRejectedValue(
          new DOMException("The operation was aborted.", "TimeoutError"),
        );

      await expect(
        fn({ gatewayUrl: "https://gateway.timeout-test" }),
      ).resolves.toEqual([]);

      expect(fetchMock).toHaveBeenCalledTimes(1);
      const init = fetchMock.mock.calls[0]?.[1] as RequestInit | undefined;
      expect(init?.signal).toBeInstanceOf(AbortSignal);
    },
  );
});

describe("gateway models cache", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const modelsResponse = (allowed: boolean) =>
    new Response(
      JSON.stringify({
        object: "list",
        data: [
          {
            id: "claude-opus-4-8",
            owned_by: "anthropic",
            context_window: 200000,
            supports_streaming: true,
            supports_vision: true,
            allowed,
          },
        ],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );

  // Restriction marks are org-scoped: an org switch swaps the token in the
  // same process, and the old org's marks must not be served to the new one.
  it("does not serve one token's marks to another token", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(modelsResponse(false))
      .mockResolvedValueOnce(modelsResponse(true));
    const gatewayUrl = "https://gateway.token-key-test";

    const first = await fetchGatewayModels({ gatewayUrl, authToken: "tok-a" });
    const second = await fetchGatewayModels({ gatewayUrl, authToken: "tok-b" });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(first[0]?.allowed).toBe(false);
    expect(second[0]?.allowed).toBe(true);
  });

  it("does not serve one project's marks to another project using the same token", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(modelsResponse(false))
      .mockResolvedValueOnce(modelsResponse(true));
    const gatewayUrl = "https://gateway.project-key-test";

    await fetchGatewayModels({ gatewayUrl, authToken: "tok-a", projectId: 1 });
    const second = await fetchGatewayModels({
      gatewayUrl,
      authToken: "tok-a",
      projectId: 2,
    });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[1]?.headers).toMatchObject({
      Authorization: "Bearer tok-a",
      "X-PostHog-Project-Id": "2",
    });
    expect(second[0]?.allowed).toBe(true);
  });

  it("serves the cached list to the same token without refetching", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(modelsResponse(false));
    const gatewayUrl = "https://gateway.token-cache-hit-test";

    await fetchGatewayModels({ gatewayUrl, authToken: "tok-a" });
    const cached = await fetchGatewayModels({ gatewayUrl, authToken: "tok-a" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(cached[0]?.allowed).toBe(false);
  });
});

describe("Go gateway model entries", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const goEntries = [
    { id: "claude-opus-5", object: "model", owned_by: "anthropic" },
    { id: "gpt-6-sol", object: "model", owned_by: "openai" },
  ];

  it("reads entries without marks from a slugless URL as allowed", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ object: "list", data: goEntries }), {
        status: 200,
      }),
    );

    const models = await fetchModelsList({
      gatewayUrl: "http://127.0.0.1:4100/go-slugless",
      authToken: "posthog-code-auth-proxy",
    });

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      "http://127.0.0.1:4100/go-slugless/v1/models",
    );
    expect(models).toEqual([
      expect.objectContaining({ id: "claude-opus-5", allowed: true }),
      expect.objectContaining({ id: "gpt-6-sol", allowed: true }),
    ]);
  });

  it("keeps the proxy's marks on Go entries", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          object: "list",
          data: [
            {
              ...goEntries[0],
              allowed: false,
              restriction_reason: "paid_plan_required",
            },
            { ...goEntries[1], allowed: true, restriction_reason: null },
          ],
        }),
        { status: 200 },
      ),
    );

    const models = await fetchGatewayModels({
      gatewayUrl: "http://127.0.0.1:4100/go-marked",
      authToken: "posthog-code-auth-proxy",
    });

    expect(models.map((m) => [m.id, m.allowed])).toEqual([
      ["claude-opus-5", false],
      ["gpt-6-sol", true],
    ]);
  });
});
