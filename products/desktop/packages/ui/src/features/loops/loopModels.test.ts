import type {
  SessionConfigOption,
  SessionConfigSelectOptions,
} from "@agentclientprotocol/sdk";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { restrictedModelMeta } from "@posthog/shared";
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

/** What the picker reads while the catalog gates no model. */
const noFlags: ModelRolloutFlags = {};

const claudeOptions = modelConfigOption([
  { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
  { value: "@cf/zai-org/glm-5.2", name: "GLM-5.2" },
]);

describe("loopModelOptions", () => {
  it("includes GPT-6 Astra in the offline Codex fallback", () => {
    expect(
      loopModelOptions("codex", [], {
        flags: noFlags,
        pinnedModel: "",
      }),
    ).toContainEqual({ value: "gpt-6-astra", label: "GPT-6 Astra" });
  });

  it("maps served model options to value/label pairs", () => {
    expect(
      loopModelOptions("claude", claudeOptions, {
        flags: noFlags,
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
        flags: noFlags,
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
        flags: noFlags,
        pinnedModel: "",
      }),
    ).toEqual([{ value: "claude-sonnet-5", label: "Claude Sonnet 5" }]);
  });

  // The open-weights models ran on the claude harness while their rollout flags were
  // already on for everyone, and the pickers kept hiding them, so each id is named here.
  it.each([
    { name: "GLM-5.2", id: "@cf/zai-org/glm-5.2" },
    { name: "GLM-5.3", id: "zai-org/glm-5.3" },
    { name: "GLM-5.3 Flash", id: "zai-org/glm-5.3-flash" },
    { name: "DeepSeek V4 Flash", id: "deepseek-ai/deepseek-v4-flash-0731" },
    { name: "Kimi K3", id: "moonshotai/kimi-k3" },
  ])("offers a served $name to everyone", ({ name, id }) => {
    const options = modelConfigOption([
      { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
      { value: id, name },
    ]);

    const values = loopModelOptions("claude", options, {
      flags: noFlags,
      pinnedModel: "",
    }).map((option) => option.value);
    expect(values).toEqual(["claude-sonnet-5", id]);
  });

  it("keeps a pinned model that the catalog no longer serves", () => {
    expect(
      loopModelOptions("claude", claudeOptions, {
        flags: noFlags,
        pinnedModel: "claude-opus-4-1",
      }),
    ).toContainEqual({ value: "claude-opus-4-1", label: "Claude Opus 4.1" });
  });

  it.each<{
    name: string;
    adapter: LoopSchemas.LoopRuntimeAdapterEnum;
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
        "zai-org/glm-5.3",
        "zai-org/glm-5.3-flash",
        "moonshotai/kimi-k3",
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
  ])("$name", ({ adapter, expectedValues }) => {
    const values = loopModelOptions(adapter, [], {
      flags: noFlags,
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
        flags: noFlags,
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
