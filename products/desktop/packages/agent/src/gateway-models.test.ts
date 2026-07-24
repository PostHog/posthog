import { afterEach, describe, expect, it, vi } from "vitest";
import {
  compareModelsForPicker,
  fetchGatewayModels,
  fetchModelsList,
  formatGatewayModelName,
  type GatewayModel,
  getClaudeModelRecency,
  isAnthropicModel,
  isBlockedModelId,
  isCloudflareModel,
  pickAllowedModel,
} from "./gateway-models";

const model = (id: string, owned_by = ""): GatewayModel => ({
  id,
  owned_by,
  context_window: 128000,
  supports_streaming: true,
  supports_vision: false,
  allowed: true,
});

describe("formatGatewayModelName", () => {
  it("keeps Claude models in friendly title case", () => {
    expect(
      formatGatewayModelName({
        id: "claude-opus-4-8",
        owned_by: "anthropic",
        context_window: 200000,
        supports_streaming: true,
        supports_vision: true,
        allowed: true,
      }),
    ).toBe("Claude Opus 4.8");
  });

  it("uppercases the GPT acronym in OpenAI model ids", () => {
    expect(
      formatGatewayModelName({
        id: "GPT-5.5",
        owned_by: "openai",
        context_window: 200000,
        supports_streaming: true,
        supports_vision: true,
        allowed: true,
      }),
    ).toBe("GPT-5.5");
  });

  it("strips the openai/ prefix, uppercases GPT, and title-cases the suffix", () => {
    expect(
      formatGatewayModelName({
        id: "openai/gpt-5.6-sol",
        owned_by: "openai",
        context_window: 200000,
        supports_streaming: true,
        supports_vision: true,
        allowed: true,
      }),
    ).toBe("GPT-5.6 Sol");
  });

  it("formats Cloudflare models as the final path segment with GLM uppercased", () => {
    expect(
      formatGatewayModelName({
        id: "@cf/zai-org/glm-5.2",
        owned_by: "cloudflare",
        context_window: 128000,
        supports_streaming: true,
        supports_vision: false,
        allowed: true,
      }),
    ).toBe("GLM-5.2");
  });

  it("leaves non-acronym Cloudflare models lowercase", () => {
    expect(
      formatGatewayModelName({
        id: "@cf/meta/llama-3.1-8b-instruct",
        owned_by: "cloudflare",
        context_window: 128000,
        supports_streaming: true,
        supports_vision: false,
        allowed: true,
      }),
    ).toBe("llama-3.1-8b-instruct");
  });

  it("blocks deprecated Claude gateway models", () => {
    expect(isBlockedModelId("claude-opus-4-5")).toBe(true);
    expect(isBlockedModelId("claude-opus-4-6")).toBe(true);
    expect(isBlockedModelId("claude-sonnet-4-5")).toBe(true);
    expect(isBlockedModelId("claude-haiku-4-5")).toBe(true);
    expect(isBlockedModelId("ANTHROPIC/CLAUDE-HAIKU-4-5")).toBe(true);
  });

  it("blocks deprecated Codex gateway models", () => {
    expect(isBlockedModelId("gpt-5.2")).toBe(true);
    expect(isBlockedModelId("gpt-5.3")).toBe(true);
    expect(isBlockedModelId("gpt-5.3-codex")).toBe(true);
    expect(isBlockedModelId("openai/gpt-5.2")).toBe(true);
    expect(isBlockedModelId("OPENAI/GPT-5.3")).toBe(true);
    expect(isBlockedModelId("OPENAI/GPT-5.3-CODEX")).toBe(true);
  });
});

describe("getClaudeModelRecency", () => {
  it.each([
    ["claude-haiku-4-5", 4005],
    ["claude-sonnet-4-6", 4006],
    ["claude-opus-4-7", 4007],
    ["claude-opus-4-8", 4008],
    ["claude-sonnet-5", 5000],
    ["claude-fable-5", 5000],
  ])("ranks %s by its embedded version (%i)", (modelId, rank) => {
    expect(getClaudeModelRecency(modelId)).toBe(rank);
  });

  it("ignores a trailing date suffix when reading the version", () => {
    expect(getClaudeModelRecency("claude-haiku-4-5-20251001")).toBe(4005);
  });

  it("ranks a model with no recognisable version as newest", () => {
    expect(getClaudeModelRecency("claude-mystery")).toBe(
      Number.MAX_SAFE_INTEGER,
    );
    expect(getClaudeModelRecency("claude-mystery")).toBeGreaterThan(
      getClaudeModelRecency("claude-fable-5"),
    );
  });
});

describe("compareModelsForPicker", () => {
  it("groups models by family least capable first, newest version first", () => {
    // The picker opens upward, so least-capable-first DOM order puts the most
    // capable family (Fable) nearest the trigger — the visual top of the menu.
    // Models as the gateway might return them — arbitrary order.
    const gatewayOrder = [
      "claude-fable-5",
      "claude-opus-4-7",
      "claude-mystery",
      "claude-sonnet-5",
      "claude-haiku-4-5",
      "claude-sonnet-4-6",
      "claude-opus-4-8",
    ];
    const displayed = [...gatewayOrder].sort(compareModelsForPicker);
    expect(displayed).toEqual([
      "claude-haiku-4-5",
      "claude-sonnet-5",
      "claude-sonnet-4-6",
      "claude-opus-4-8",
      "claude-opus-4-7",
      "claude-fable-5",
      "claude-mystery",
    ]);
  });
});

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

  it("corrects stale GLM 5.2 context-window metadata", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          object: "list",
          data: [
            {
              id: "@cf/zai-org/glm-5.2",
              owned_by: "cloudflare",
              context_window: 128_000,
              supports_streaming: true,
              supports_vision: false,
            },
          ],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const models = await fetchGatewayModels({
      gatewayUrl: "https://gateway.glm-context-test",
    });

    expect(models[0]?.context_window).toBe(1_000_000);
  });
});

describe("isCloudflareModel", () => {
  it.each([
    { id: "@cf/zai-org/glm-5.2", owned_by: "cloudflare", expected: true },
    { id: "claude-opus-4-8", owned_by: "anthropic", expected: false },
    { id: "@cf/zai-org/glm-5.2", owned_by: "", expected: true },
    { id: "gpt-5.5", owned_by: "", expected: false },
    // A Cloudflare-served model can report an upstream owner; the `@cf/` prefix still wins.
    { id: "@cf/openai/gpt-oss", owned_by: "openai", expected: true },
  ])(
    "isCloudflareModel($id, owned_by=$owned_by) → $expected",
    ({ id, owned_by, expected }) => {
      expect(isCloudflareModel(model(id, owned_by))).toBe(expected);
    },
  );

  it("does not classify Cloudflare models as Anthropic", () => {
    // The Claude adapter accepts both, but they must stay distinguishable.
    const glm = model("@cf/zai-org/glm-5.2", "cloudflare");
    expect(isCloudflareModel(glm)).toBe(true);
    expect(isAnthropicModel(glm)).toBe(false);
  });
});

describe("pickAllowedModel", () => {
  const entry = (id: string, allowed: boolean) => ({ id, allowed });

  it.each([
    [
      "keeps an allowed preferred model",
      [entry("claude-opus-4-8", true)],
      "claude-opus-4-8",
      "claude-opus-4-8",
    ],
    [
      "keeps a preferred model absent from the list",
      [entry("claude-opus-4-8", true)],
      "claude-sonnet-5",
      "claude-sonnet-5",
    ],
    [
      "moves a restricted preferred model to the newest allowed one",
      [
        entry("claude-opus-4-8", false),
        entry("claude-sonnet-4-6", true),
        entry("@cf/zai-org/glm-5.2", true),
      ],
      "claude-opus-4-8",
      "@cf/zai-org/glm-5.2",
    ],
    [
      "keeps the preferred model when everything is restricted",
      [entry("claude-opus-4-8", false)],
      "claude-opus-4-8",
      "claude-opus-4-8",
    ],
    [
      "keeps the preferred model when the list is empty",
      [],
      "claude-opus-4-8",
      "claude-opus-4-8",
    ],
  ] as const)("%s", (_name, models, preferred, expected) => {
    expect(pickAllowedModel(models, preferred)).toBe(expected);
  });
});
