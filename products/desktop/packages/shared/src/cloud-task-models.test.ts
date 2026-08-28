import { describe, expect, it } from "vitest";
import {
  buildCloudTaskConfigOptions,
  compareModelsForPicker,
  formatGatewayModelName,
  type GatewayModel,
  getClaudeModelRecency,
  isAnthropicModel,
  isBasetenModel,
  isBlockedModelId,
  isCloudflareModel,
  isDeepseekModelId,
  isModalModel,
  isModalModelId,
  normalizeGatewayModelsResponse,
  pickAllowedModel,
} from "./cloud-task-models";

const model = (
  id: string,
  owned_by = "anthropic",
  allowed = true,
): GatewayModel => ({
  id,
  owned_by,
  context_window: 128000,
  supports_streaming: true,
  supports_vision: false,
  allowed,
});

describe("formatGatewayModelName", () => {
  it.each([
    [model("claude-opus-4-8"), "Claude Opus 4.8"],
    [model("GPT-5.5", "openai"), "GPT-5.5"],
    [model("openai/gpt-5.6-sol", "openai"), "GPT-5.6 Sol"],
    [model("moonshotai/kimi-k3", "modal"), "Kimi K3"],
    [model("@cf/zai-org/glm-5.2", "cloudflare"), "GLM-5.2"],
    [model("zai-org/glm-5.3", "baseten"), "GLM-5.3"],
    [model("zai-org/glm-5.3-flash", "baseten"), "GLM-5.3 Flash"],
    [
      model("deepseek-ai/deepseek-v4-flash-0731", "baseten"),
      "DeepSeek V4 Flash",
    ],
    [
      model("@cf/meta/llama-3.1-8b-instruct", "cloudflare"),
      "llama-3.1-8b-instruct",
    ],
  ])("formats $id", (gatewayModel, expected) => {
    expect(formatGatewayModelName(gatewayModel)).toBe(expected);
  });
});

describe("normalizeGatewayModelsResponse", () => {
  it("passes through the gateway's advertised context window for GLM 5.2 unmodified", () => {
    const models = normalizeGatewayModelsResponse([
      model("@cf/zai-org/glm-5.2", "cloudflare"),
    ]);

    expect(models[0]?.context_window).toBe(128000);
  });

  it("does not override any model's context window", () => {
    const models = normalizeGatewayModelsResponse([
      { ...model("@cf/zai-org/glm-5.2", "cloudflare"), context_window: 256000 },
    ]);

    expect(models[0]?.context_window).toBe(256000);
  });
});

describe("isBlockedModelId", () => {
  it.each([
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-sonnet-4-5",
    "ANTHROPIC/CLAUDE-HAIKU-4-5",
    "gpt-5.2",
    "gpt-5.3",
    "gpt-5.3-codex",
    "OPENAI/GPT-5.3-CODEX",
  ])("blocks %s", (modelId) => {
    expect(isBlockedModelId(modelId)).toBe(true);
  });
});

describe("getClaudeModelRecency", () => {
  it.each([
    ["claude-haiku-4-5", 4005],
    ["claude-sonnet-4-6", 4006],
    ["claude-opus-4-7", 4007],
    ["claude-opus-4-8", 4008],
    ["claude-sonnet-5", 5000],
  ])("ranks %s", (modelId, expected) => {
    expect(getClaudeModelRecency(modelId)).toBe(expected);
  });

  it("ignores trailing dates and ranks unknown versions newest", () => {
    expect(getClaudeModelRecency("claude-haiku-4-5-20251001")).toBe(4005);
    expect(getClaudeModelRecency("claude-mystery")).toBe(
      Number.MAX_SAFE_INTEGER,
    );
  });
});

describe("compareModelsForPicker", () => {
  it("groups by capability and sorts newest first", () => {
    const displayed = [
      "claude-fable-5",
      "claude-opus-4-7",
      "claude-mystery",
      "claude-sonnet-5",
      "claude-haiku-4-5",
      "claude-sonnet-4-6",
      "claude-opus-4-8",
    ].sort(compareModelsForPicker);

    expect(displayed).toEqual([
      "claude-fable-5",
      "claude-opus-4-8",
      "claude-opus-4-7",
      "claude-sonnet-5",
      "claude-sonnet-4-6",
      "claude-haiku-4-5",
      "claude-mystery",
    ]);
  });
});

describe("model classification", () => {
  it("keeps Cloudflare models distinct from Anthropic", () => {
    const gatewayModel = model("@cf/openai/gpt-oss", "openai");
    expect(isCloudflareModel(gatewayModel)).toBe(true);
    expect(isAnthropicModel(gatewayModel)).toBe(false);
  });

  it("recognizes Modal models by owner and id", () => {
    const gatewayModel = model("moonshotai/kimi-k3", "modal");
    expect(isModalModel(gatewayModel)).toBe(true);
    expect(isModalModelId(gatewayModel.id)).toBe(true);
  });

  it("recognizes Baseten models by owner and id", () => {
    const gatewayModel = model("deepseek-ai/deepseek-v4-flash-0731", "baseten");
    expect(isBasetenModel(gatewayModel)).toBe(true);
    expect(isDeepseekModelId(gatewayModel.id)).toBe(true);
    expect(isAnthropicModel(gatewayModel)).toBe(false);
    expect(isBasetenModel(model("claude-opus-4-8"))).toBe(false);
  });
});

describe("pickAllowedModel", () => {
  const entry = (id: string, allowed: boolean) => ({ id, allowed });

  it.each([
    [[entry("claude-opus-4-8", true)], "claude-opus-4-8", "claude-opus-4-8"],
    [[entry("claude-opus-4-8", true)], "claude-sonnet-5", "claude-sonnet-5"],
    [
      [
        entry("claude-opus-4-8", false),
        entry("claude-sonnet-4-6", true),
        entry("@cf/zai-org/glm-5.2", true),
      ],
      "claude-opus-4-8",
      "@cf/zai-org/glm-5.2",
    ],
    [[entry("claude-opus-4-8", false)], "claude-opus-4-8", "claude-opus-4-8"],
    [[], "claude-opus-4-8", "claude-opus-4-8"],
  ] as const)("selects an allowed default", (models, preferred, expected) => {
    expect(pickAllowedModel(models, preferred)).toBe(expected);
  });
});

describe("buildCloudTaskConfigOptions", () => {
  it("builds Claude options with restrictions and reasoning policy", () => {
    const options = buildCloudTaskConfigOptions(
      [
        model("gpt-5.5", "openai"),
        model("claude-opus-4-7", "anthropic"),
        model("claude-opus-4-8", "anthropic", false),
        model("@cf/zai-org/glm-5.2", "cloudflare"),
      ],
      "claude",
    );

    expect(options).toMatchObject([
      { id: "mode", currentValue: "plan" },
      {
        id: "model",
        currentValue: "@cf/zai-org/glm-5.2",
        options: [
          { value: "claude-opus-4-7" },
          {
            value: "claude-opus-4-8",
            _meta: { "posthog.code/restrictedModel": true },
          },
          { value: "@cf/zai-org/glm-5.2" },
        ],
      },
      {
        id: "effort",
        currentValue: "high",
        options: [{ value: "high" }, { value: "max" }],
      },
    ]);
    expect(options.map((option) => option.id)).toEqual([
      "mode",
      "model",
      "effort",
    ]);
  });

  it("builds Codex options with the shared default and reasoning levels", () => {
    const options = buildCloudTaskConfigOptions(
      [
        model("claude-opus-4-8"),
        model("gpt-5.6", "openai"),
        model("gpt-5.5", "openai"),
      ],
      "codex",
    );

    expect(options).toMatchObject([
      { id: "mode", currentValue: "auto" },
      {
        id: "model",
        currentValue: "gpt-5.5",
        options: [{ value: "gpt-5.6" }, { value: "gpt-5.5" }],
      },
      {
        id: "reasoning_effort",
        currentValue: "high",
        options: [
          { value: "low" },
          { value: "medium" },
          { value: "high" },
          { value: "xhigh" },
        ],
      },
    ]);
  });

  it("offers Modal models to Claude sessions", () => {
    const options = buildCloudTaskConfigOptions(
      [model("moonshotai/kimi-k3", "modal")],
      "claude",
    );

    expect(options.find((option) => option.id === "model")?.options).toEqual([
      expect.objectContaining({
        value: "moonshotai/kimi-k3",
        name: "Kimi K3",
      }),
    ]);
  });

  it("offers Baseten models to Claude sessions but not Codex", () => {
    const models = [model("deepseek-ai/deepseek-v4-flash-0731", "baseten")];

    const claudeModelOptions = buildCloudTaskConfigOptions(
      models,
      "claude",
    ).find((option) => option.id === "model")?.options;
    expect(claudeModelOptions).toEqual([
      expect.objectContaining({
        value: "deepseek-ai/deepseek-v4-flash-0731",
        name: "DeepSeek V4 Flash",
      }),
    ]);

    const codexModelOptions = buildCloudTaskConfigOptions(models, "codex").find(
      (option) => option.id === "model",
    )?.options;
    expect(codexModelOptions).not.toContainEqual(
      expect.objectContaining({ value: "deepseek-ai/deepseek-v4-flash-0731" }),
    );
  });
});
