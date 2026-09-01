import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import {
  formatCodexModelName,
  getReasoningEffortOptions,
  modelIdFromConfigOptions,
  supportsMaxEffort,
  supportsXhighEffort,
} from "./models";

describe("formatCodexModelName", () => {
  it("uses raw lowercase model ids", () => {
    expect(formatCodexModelName("GPT-5.5")).toBe("gpt-5.5");
  });
});

describe("getReasoningEffortOptions", () => {
  const values = (modelId: string) =>
    getReasoningEffortOptions(modelId).map((o) => o.value);

  it.each(["gpt-5.5", "gpt-5.5-codex", "openai/gpt-5.5", "GPT-5.5"])(
    "offers Extra High for the gpt-5.5 family (%s)",
    (modelId) => {
      expect(values(modelId)).toEqual(["low", "medium", "high", "xhigh"]);
    },
  );

  it.each([
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "openai/gpt-5.6-sol",
    "GPT-5.6-SOL",
  ])("offers Max for the gpt-5.6 family (%s)", (modelId) => {
    expect(values(modelId)).toEqual(["low", "medium", "high", "xhigh", "max"]);
  });

  it.each(["gpt-5.3-codex", "gpt-5.1", "o3"])(
    "caps at High for other models (%s)",
    (modelId) => {
      expect(values(modelId)).toEqual(["low", "medium", "high"]);
    },
  );

  it('labels the extra tier "Extra High"', () => {
    const xhigh = getReasoningEffortOptions("gpt-5.5").find(
      (o) => o.value === "xhigh",
    );
    expect(xhigh?.name).toBe("Extra High");
  });
});

describe("supportsXhighEffort", () => {
  it("is true for the gpt-5.5 family and false for other models", () => {
    expect(supportsXhighEffort("gpt-5.5-codex")).toBe(true);
    expect(supportsXhighEffort("GPT-5.5")).toBe(true);
    expect(supportsXhighEffort("gpt-5.3-codex")).toBe(false);
  });
});

describe("supportsMaxEffort", () => {
  it("is true only for the gpt-5.6 family", () => {
    expect(supportsMaxEffort("gpt-5.6-sol")).toBe(true);
    expect(supportsMaxEffort("GPT-5.6-LUNA")).toBe(true);
    expect(supportsMaxEffort("gpt-5.5")).toBe(false);
  });
});

describe("modelIdFromConfigOptions", () => {
  const modelOption = (currentValue: unknown): SessionConfigOption =>
    ({
      id: "model",
      name: "Model",
      type: "select",
      category: "model",
      currentValue,
      options: [],
    }) as unknown as SessionConfigOption;

  it("returns the currentValue of the model-category option", () => {
    expect(modelIdFromConfigOptions([modelOption("gpt-5.5-codex")])).toBe(
      "gpt-5.5-codex",
    );
  });

  it("ignores non-model categories", () => {
    const modeOption = {
      id: "mode",
      name: "Mode",
      type: "select",
      category: "mode",
      currentValue: "auto",
      options: [],
    } as unknown as SessionConfigOption;
    expect(modelIdFromConfigOptions([modeOption])).toBeUndefined();
  });

  it("returns undefined when currentValue is not a string", () => {
    expect(modelIdFromConfigOptions([modelOption(null)])).toBeUndefined();
    expect(modelIdFromConfigOptions([modelOption(123)])).toBeUndefined();
  });

  it("returns undefined for null/undefined input", () => {
    expect(modelIdFromConfigOptions(null)).toBeUndefined();
    expect(modelIdFromConfigOptions(undefined)).toBeUndefined();
  });
});
