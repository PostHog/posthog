import type { Api, Model } from "@earendil-works/pi-ai";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { describe, expect, it, vi } from "vitest";
import {
  resolveModelAuth,
  resolveModelAuthWithFallback,
  SubagentAuthError,
  writeAuthBridgeExtension,
} from "./auth";

function makeModel(overrides: Partial<Model<Api>> = {}): Model<Api> {
  return {
    id: "sonnet",
    name: "Sonnet",
    api: "anthropic-messages",
    provider: "anthropic",
    baseUrl: "https://api.anthropic.com",
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 200000,
    maxTokens: 8192,
    ...overrides,
  } as Model<Api>;
}

function makeCtx(options: {
  model?: Model<Api>;
  allModels?: Model<Api>[];
  apiKeyResult?: {
    ok: boolean;
    apiKey?: string;
    headers?: Record<string, string>;
  };
}): ExtensionContext {
  const apiKeyResult = options.apiKeyResult ?? { ok: true, apiKey: "test-key" };
  return {
    model: options.model,
    modelRegistry: {
      find: vi.fn((provider: string, id: string) =>
        (options.allModels ?? []).find(
          (m) => m.provider === provider && m.id === id,
        ),
      ),
      getAll: vi.fn(() => options.allModels ?? []),
      getApiKeyAndHeaders: vi.fn(async () => apiKeyResult),
    },
  } as unknown as ExtensionContext;
}

describe("resolveModelAuth", () => {
  it("uses the parent's current model when request.model is unset", async () => {
    const model = makeModel();
    const ctx = makeCtx({ model });
    const result = await resolveModelAuth(ctx, { requestedBy: "worker" });
    expect(result.model).toBe(model);
    expect(result.apiKey).toBe("test-key");
  });

  it("resolves request.model as 'provider/id' via modelRegistry.find", async () => {
    const wanted = makeModel({ provider: "openai", id: "gpt-5" });
    const ctx = makeCtx({ model: makeModel(), allModels: [wanted] });
    const result = await resolveModelAuth(ctx, {
      requestedBy: "worker",
      model: "openai/gpt-5",
    });
    expect(result.model).toBe(wanted);
  });

  it("resolves a bare request.model id against the parent's current provider", async () => {
    const current = makeModel({ provider: "anthropic", id: "haiku" });
    const wanted = makeModel({ provider: "anthropic", id: "opus" });
    const ctx = makeCtx({ model: current, allModels: [wanted] });
    const result = await resolveModelAuth(ctx, {
      requestedBy: "worker",
      model: "opus",
    });
    expect(result.model).toBe(wanted);
  });

  it("throws SubagentAuthError for an unknown request.model", async () => {
    const ctx = makeCtx({ model: makeModel() });
    await expect(
      resolveModelAuth(ctx, { requestedBy: "worker", model: "nope/nope" }),
    ).rejects.toThrow(SubagentAuthError);
  });

  it("throws SubagentAuthError when there is no active model at all", async () => {
    const ctx = makeCtx({ model: undefined });
    await expect(
      resolveModelAuth(ctx, { requestedBy: "worker" }),
    ).rejects.toThrow(SubagentAuthError);
  });

  it("throws SubagentAuthError when credentials can't be resolved", async () => {
    const ctx = makeCtx({ model: makeModel(), apiKeyResult: { ok: false } });
    await expect(
      resolveModelAuth(ctx, { requestedBy: "worker" }),
    ).rejects.toThrow(SubagentAuthError);
  });
});

describe("resolveModelAuthWithFallback", () => {
  it("falls back to the next model when the primary has no credentials", async () => {
    const primary = makeModel({ provider: "anthropic", id: "opus" });
    const fallback = makeModel({ provider: "anthropic", id: "haiku" });
    const ctx = makeCtx({ model: primary, allModels: [primary, fallback] });
    ctx.modelRegistry.getApiKeyAndHeaders = vi.fn(async (model: Model<Api>) =>
      model.id === "opus"
        ? { ok: false as const, error: "no auth" }
        : { ok: true as const, apiKey: "fallback-key" },
    );

    const result = await resolveModelAuthWithFallback(
      ctx,
      "worker",
      "anthropic/opus",
      ["anthropic/haiku"],
    );
    expect(result.model.id).toBe("haiku");
    expect(result.apiKey).toBe("fallback-key");
  });

  it("throws the last error when nothing in the fallback chain works", async () => {
    const ctx = makeCtx({ model: makeModel(), apiKeyResult: { ok: false } });
    await expect(
      resolveModelAuthWithFallback(ctx, "worker", undefined, []),
    ).rejects.toThrow(SubagentAuthError);
  });
});

describe("writeAuthBridgeExtension", () => {
  it("writes a module that registers the resolved provider/model/apiKey", async () => {
    const model = makeModel({ provider: "posthog", id: "claude-sonnet" });
    const { dir, filePath } = await writeAuthBridgeExtension({
      model,
      apiKey: "secret-key",
    });
    try {
      const mod = (await import(filePath)) as {
        default: (pi: {
          registerProvider: (...args: unknown[]) => void;
        }) => void;
      };
      const registerProvider = vi.fn();
      mod.default({ registerProvider });

      expect(registerProvider).toHaveBeenCalledTimes(1);
      const [providerName, config] = registerProvider.mock.calls[0] as [
        string,
        Record<string, unknown>,
      ];
      expect(providerName).toBe("posthog");
      expect(config.apiKey).toBe("secret-key");
      expect((config.models as Array<{ id: string }>)[0].id).toBe(
        "claude-sonnet",
      );
    } finally {
      const fs = await import("node:fs/promises");
      await fs.rm(dir, { recursive: true, force: true });
    }
  });
});
