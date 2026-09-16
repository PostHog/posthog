import type {
  SessionConfigOption,
  SessionConfigSelectOptions,
} from "@agentclientprotocol/sdk";
import type { LoopSchemas } from "@posthog/api-client/loops";
import {
  DEEPSEEK_MODEL_FLAG,
  GLM_MODEL_FLAG,
  GLM53_FLASH_MODEL_FLAG,
  GLM53_MODEL_FLAG,
  KIMI_MODEL_FLAG,
  restrictedModelMeta,
} from "@posthog/shared";
import { MODELS } from "@posthog/shared/model-catalog";
import { describe, expect, it } from "vitest";
import type { ModelRolloutFlags } from "../sessions/modelOptionFilters";
import {
  clampLoopReasoningEffort,
  LOOP_DEFAULT_MODELS,
  loopModelOptions,
  loopReasoningEffortOptions,
} from "./loopModels";

function modelConfigOption(
  options: SessionConfigSelectOptions,
): SessionConfigOption[] {
  return [
    {
      type: "select",
      id: "model",
      name: "Model",
      category: "model",
      currentValue: "claude-sonnet-5",
      options,
    },
  ];
}

/** The flag record the picker reads, from the friendlier names these cases are written in. */
function rolloutFlags(on: {
  glm?: boolean;
  glm53?: boolean;
  glm53Flash?: boolean;
  kimi?: boolean;
  deepseek?: boolean;
}): ModelRolloutFlags {
  return {
    [GLM_MODEL_FLAG]: on.glm ?? false,
    [GLM53_MODEL_FLAG]: on.glm53 ?? false,
    [GLM53_FLASH_MODEL_FLAG]: on.glm53Flash ?? false,
    [KIMI_MODEL_FLAG]: on.kimi ?? false,
    [DEEPSEEK_MODEL_FLAG]: on.deepseek ?? false,
  };
}

const claudeOptions = modelConfigOption([
  { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
  { value: "@cf/zai-org/glm-5.2", name: "GLM-5.2" },
]);

describe("loopModelOptions", () => {
  it("includes GPT-6 Astra in the offline Codex fallback", () => {
    expect(
      loopModelOptions("codex", [], {
        flags: rolloutFlags({ glm: false }),
        pinnedModel: "",
      }),
    ).toContainEqual({ value: "gpt-6-astra", label: "GPT-6 Astra" });
  });

  it("maps served model options to value/label pairs", () => {
    expect(
      loopModelOptions("claude", claudeOptions, {
        flags: rolloutFlags({ glm: true }),
        pinnedModel: "",
      }),
    ).toEqual([
      { value: "claude-sonnet-5", label: "Claude Sonnet 5" },
      { value: "@cf/zai-org/glm-5.2", label: "GLM-5.2" },
    ]);
  });

  it("flattens grouped select options", () => {
    const grouped = modelConfigOption([
      {
        group: "anthropic",
        name: "Anthropic",
        options: [{ value: "claude-sonnet-5", name: "Claude Sonnet 5" }],
      },
    ]);
    expect(
      loopModelOptions("claude", grouped, {
        flags: rolloutFlags({ glm: true }),
        pinnedModel: "",
      }),
    ).toEqual([{ value: "claude-sonnet-5", label: "Claude Sonnet 5" }]);
  });

  it("drops plan-restricted models", () => {
    const withRestricted = modelConfigOption([
      { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
      {
        value: "claude-fable-5",
        name: "Claude Fable 5",
        _meta: restrictedModelMeta(),
      },
    ]);
    expect(
      loopModelOptions("claude", withRestricted, {
        flags: rolloutFlags({ glm: true }),
        pinnedModel: "",
      }),
    ).toEqual([{ value: "claude-sonnet-5", label: "Claude Sonnet 5" }]);
  });

  it.each([
    {
      name: "hides GLM when the flag is off",
      glmEnabled: false,
      pinnedModel: "",
      expectedValues: ["claude-sonnet-5"],
    },
    {
      name: "shows GLM when the flag is on",
      glmEnabled: true,
      pinnedModel: "",
      expectedValues: ["claude-sonnet-5", "@cf/zai-org/glm-5.2"],
    },
    {
      name: "keeps a pinned GLM model visible with the flag off",
      glmEnabled: false,
      pinnedModel: "@cf/zai-org/glm-5.2",
      expectedValues: ["claude-sonnet-5", "@cf/zai-org/glm-5.2"],
    },
  ])("$name", ({ glmEnabled, pinnedModel, expectedValues }) => {
    const values = loopModelOptions("claude", claudeOptions, {
      flags: rolloutFlags({ glm: glmEnabled }),
      pinnedModel,
    }).map((option) => option.value);
    expect(values).toEqual(expectedValues);
  });

  it("keeps a pinned model that the catalog no longer serves", () => {
    expect(
      loopModelOptions("claude", claudeOptions, {
        flags: rolloutFlags({ glm: true }),
        pinnedModel: "claude-opus-4-1",
      }),
    ).toContainEqual({ value: "claude-opus-4-1", label: "Claude Opus 4.1" });
  });

  it.each([
    {
      flags: rolloutFlags({ glm53: true }),
      expected: [{ value: "zai-org/glm-5.3", label: "GLM-5.3" }],
    },
    {
      flags: rolloutFlags({ glm53Flash: true }),
      expected: [{ value: "zai-org/glm-5.3-flash", label: "GLM-5.3 Flash" }],
    },
  ])("gates each GLM 5.3 variant independently", ({ flags, expected }) => {
    const options = modelConfigOption([
      { value: "@cf/zai-org/glm-5.2", name: "GLM-5.2" },
      { value: "zai-org/glm-5.3", name: "GLM-5.3" },
      { value: "zai-org/glm-5.3-flash", name: "GLM-5.3 Flash" },
    ]);

    expect(
      loopModelOptions("claude", options, { flags, pinnedModel: "" }),
    ).toEqual(expected);
  });

  it.each([
    {
      name: "hides a served DeepSeek model when the flag is off",
      deepseekEnabled: false,
      pinnedModel: "",
      expectedValues: ["claude-sonnet-5"],
    },
    {
      name: "shows a served DeepSeek model when the flag is on",
      deepseekEnabled: true,
      pinnedModel: "",
      expectedValues: ["claude-sonnet-5", "deepseek-ai/deepseek-v4-flash-0731"],
    },
    {
      name: "keeps a pinned DeepSeek model visible with the flag off",
      deepseekEnabled: false,
      pinnedModel: "deepseek-ai/deepseek-v4-flash-0731",
      expectedValues: ["claude-sonnet-5", "deepseek-ai/deepseek-v4-flash-0731"],
    },
  ])("$name", ({ deepseekEnabled, pinnedModel, expectedValues }) => {
    const options = modelConfigOption([
      { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
      {
        value: "deepseek-ai/deepseek-v4-flash-0731",
        name: "DeepSeek V4 Flash",
      },
    ]);

    const values = loopModelOptions("claude", options, {
      flags: rolloutFlags({ glm: true, deepseek: deepseekEnabled }),
      pinnedModel,
    }).map((option) => option.value);
    expect(values).toEqual(expectedValues);
  });

  it.each<{
    name: string;
    adapter: LoopSchemas.LoopRuntimeAdapterEnum;
    glm53Enabled?: boolean;
    expectedValues: string[];
  }>([
    {
      name: "falls back to the known claude models when the config has no model select",
      adapter: "claude",
      expectedValues: [
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-fable-5-1",
      ],
    },
    {
      name: "falls back to the known codex models when the config has no model select",
      adapter: "codex",
      expectedValues: [
        "gpt-5",
        "gpt-5.5",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-6-astra",
      ],
    },
    {
      name: "applies the GLM 5.3 flag to the fallback list",
      adapter: "claude",
      glm53Enabled: true,
      expectedValues: [
        "claude-opus-4-8",
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-fable-5",
        "claude-fable-5-1",
        "zai-org/glm-5.3",
      ],
    },
  ])("$name", ({ adapter, glm53Enabled, expectedValues }) => {
    const values = loopModelOptions(adapter, [], {
      flags: rolloutFlags({ glm: true, glm53: glm53Enabled }),
      pinnedModel: "",
    }).map((option) => option.value);
    expect(values).toEqual(expectedValues);
  });

  // The loops serializer rejects a model the catalog no longer serves, so a retired id
  // in the fallback list is a save the user cannot make. The cases above assert the
  // fallback against hardcoded ids, so only this notices a catalog removal.
  it("every fallback model is one the catalog still serves", () => {
    for (const adapter of ["claude", "codex"] as const) {
      const served = MODELS.filter((m) => m.runtimeAdapter === adapter).map(
        (m) => m.id,
      );
      const fallback = loopModelOptions(adapter, [], {
        flags: rolloutFlags({
          glm: true,
          glm53: true,
          glm53Flash: true,
          kimi: true,
          deepseek: true,
        }),
        pinnedModel: "",
      })
        .map((o) => o.value)
        .filter((v) => v !== "");
      expect(served).toEqual(expect.arrayContaining(fallback));
    }
  });
});

describe("LOOP_DEFAULT_MODELS", () => {
  it("mirrors the backend loop defaults", () => {
    expect(LOOP_DEFAULT_MODELS.claude.id).toBe("claude-sonnet-5");
    expect(LOOP_DEFAULT_MODELS.codex.id).toBe("gpt-5");
  });
});

describe("loopReasoningEffortOptions", () => {
  it.each<{
    adapter: LoopSchemas.LoopRuntimeAdapterEnum;
    model: string;
    expectedValues: LoopSchemas.LoopReasoningEffortEnum[];
  }>([
    {
      adapter: "claude",
      model: "",
      expectedValues: ["low", "medium", "high", "xhigh", "max", "ultracode"],
    },
    {
      adapter: "claude",
      model: "claude-sonnet-5",
      expectedValues: ["low", "medium", "high", "xhigh", "max", "ultracode"],
    },
    {
      adapter: "claude",
      model: "@cf/zai-org/glm-5.2",
      expectedValues: ["high", "max"],
    },
    { adapter: "claude", model: "unknown-model", expectedValues: [] },
    { adapter: "codex", model: "", expectedValues: ["low", "medium", "high"] },
    {
      adapter: "codex",
      model: "gpt-5.5",
      expectedValues: ["low", "medium", "high", "xhigh"],
    },
    {
      adapter: "codex",
      model: "gpt-5.6-sol",
      expectedValues: ["low", "medium", "high", "xhigh", "max"],
    },
  ])(
    "$adapter with model '$model' offers $expectedValues",
    ({ adapter, model, expectedValues }) => {
      expect(
        loopReasoningEffortOptions(adapter, model).map(
          (option) => option.value,
        ),
      ).toEqual(expectedValues);
    },
  );

  it("forwards isDefault and docsUrl from the underlying option meta", () => {
    const options = loopReasoningEffortOptions("claude", "claude-sonnet-5");

    const highOption = options.find((option) => option.value === "high");
    expect(highOption?.isDefault).toBe(true);

    for (const option of options.filter((option) => option.value !== "high")) {
      expect(option.isDefault).toBeFalsy();
    }

    const ultracodeOption = options.find(
      (option) => option.value === "ultracode",
    );
    expect(ultracodeOption?.docsUrl).toBe(
      "https://code.claude.com/docs/en/workflows",
    );

    const lowOption = options.find((option) => option.value === "low");
    expect(lowOption?.docsUrl).toBeUndefined();
  });
});

describe("clampLoopReasoningEffort", () => {
  it.each<{
    name: string;
    adapter: LoopSchemas.LoopRuntimeAdapterEnum;
    model: string;
    effort: LoopSchemas.LoopReasoningEffortEnum | null;
    expected: LoopSchemas.LoopReasoningEffortEnum | null;
  }>([
    {
      name: "keeps a supported effort",
      adapter: "claude",
      model: "claude-sonnet-5",
      effort: "low",
      expected: "low",
    },
    {
      name: "clears an effort the model doesn't support",
      adapter: "claude",
      model: "@cf/zai-org/glm-5.2",
      effort: "low",
      expected: null,
    },
    {
      name: "clears an effort the default model doesn't support",
      adapter: "codex",
      model: "",
      effort: "xhigh",
      expected: null,
    },
    {
      name: "keeps auto as auto",
      adapter: "codex",
      model: "",
      effort: null,
      expected: null,
    },
    {
      name: "clears max on a codex model without it",
      adapter: "codex",
      model: "gpt-5",
      effort: "max",
      expected: null,
    },
  ])("$name", ({ adapter, model, effort, expected }) => {
    expect(clampLoopReasoningEffort(adapter, model, effort)).toBe(expected);
  });
});
