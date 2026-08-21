import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_PI_MODEL_ID,
  fetchPosthogPiModelCatalog,
  resolvePosthogPiModelCatalog,
} from "./model-catalog";

describe("resolvePosthogPiModelCatalog", () => {
  afterEach(() => {
    delete process.env.PI_OFFLINE;
    vi.unstubAllGlobals();
  });

  it("uses the PostHog provider model configuration for gateway models", () => {
    const models = resolvePosthogPiModelCatalog(
      [
        {
          id: "claude-opus-5",
          owned_by: "anthropic",
          context_window: 1_000_000,
          supports_vision: true,
          allowed: true,
        },
        {
          id: "claude-haiku-4-5",
          owned_by: "anthropic",
          context_window: 200_000,
          supports_vision: true,
          allowed: true,
        },
        {
          id: "gpt-5.6-sol",
          owned_by: "openai",
          context_window: 1_000_000,
          supports_vision: true,
          allowed: false,
        },
      ],
      "us",
    );

    expect(models).toEqual([
      expect.objectContaining({
        provider: "posthog",
        id: "claude-opus-5",
        thinkingLevels: expect.arrayContaining(["off", "high", "xhigh"]),
      }),
      expect.objectContaining({
        provider: "posthog",
        id: "claude-haiku-4-5",
      }),
    ]);
  });

  it("marks the default model without changing catalog order", () => {
    const models = resolvePosthogPiModelCatalog(
      [
        {
          id: "claude-haiku-4-5",
          context_window: 200_000,
          supports_vision: true,
          allowed: true,
        },
        {
          id: DEFAULT_PI_MODEL_ID,
          context_window: 1_000_000,
          supports_vision: true,
          allowed: true,
        },
      ],
      "us",
    );

    expect(models.map((model) => model.id)).toEqual([
      "claude-haiku-4-5",
      DEFAULT_PI_MODEL_ID,
    ]);
    expect(models.find((model) => model.isDefault)?.id).toBe(
      DEFAULT_PI_MODEL_ID,
    );
  });

  it.each([
    ["claude-haiku-4-5", "Claude Haiku 4.5"],
    ["claude-sonnet-5", "Claude Sonnet 5"],
    ["claude-fable-5", "Claude Fable 5"],
    ["claude-opus-5", "Claude Opus 5"],
    ["gpt-5.6-sol", "GPT-5.6 Sol"],
    ["gpt-5.6-terra", "GPT-5.6 Terra"],
    ["gpt-5.6-luna", "GPT-5.6 Luna"],
    ["@cf/zai-org/glm-5.2", "GLM-5.2"],
    ["moonshotai/kimi-k3", "Kimi K3"],
  ])("formats %s for Pi", (id, name) => {
    const models = resolvePosthogPiModelCatalog(
      [
        {
          id,
          context_window: 200_000,
          supports_vision: true,
          allowed: true,
        },
      ],
      "us",
    );

    expect(models).toEqual([expect.objectContaining({ id, name })]);
  });

  it("keeps unknown Pi models in the catalog", () => {
    const models = resolvePosthogPiModelCatalog(
      [
        {
          id: "new-model",
          context_window: 200_000,
          supports_vision: true,
          allowed: true,
        },
      ],
      "us",
    );

    expect(models).toEqual([
      expect.objectContaining({ id: "new-model", name: "new-model" }),
    ]);
  });

  it.each([
    "claude-sonnet-4-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-7",
    "claude-sonnet-4-8",
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
    "gpt-5.2",
    "gpt-5.3-codex",
    "gpt-5.4",
    "gpt-5.5",
    "gpt-5-mini",
  ])("excludes %s from the Pi catalog", (id) => {
    const models = resolvePosthogPiModelCatalog(
      [
        {
          id,
          context_window: 200_000,
          supports_vision: true,
          allowed: true,
        },
      ],
      "us",
    );

    expect(models).toEqual([]);
  });

  it("uses fallback models without fetching while offline", async () => {
    process.env.PI_OFFLINE = "1";
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);

    const models = await fetchPosthogPiModelCatalog(
      "https://gateway.example.com",
      "us",
    );

    expect(fetch).not.toHaveBeenCalled();
    expect(models.length).toBeGreaterThan(0);
  });
});
