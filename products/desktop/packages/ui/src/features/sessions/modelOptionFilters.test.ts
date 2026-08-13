import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { describe, expect, it } from "vitest";
import {
  stripDeepseekModelOption,
  stripKimiModelOption,
} from "./modelOptionFilters";

describe("modelOptionFilters", () => {
  it("selects an available model when Kimi is hidden", () => {
    const option: SessionConfigOption = {
      type: "select",
      id: "model",
      name: "Model",
      currentValue: "moonshotai/kimi-k3",
      options: [
        { value: "moonshotai/kimi-k3", name: "Kimi K3" },
        { value: "claude-opus-4-8", name: "Claude Opus 4.8" },
      ],
    };

    expect(stripKimiModelOption(option)).toMatchObject({
      currentValue: "claude-opus-4-8",
      options: [{ value: "claude-opus-4-8" }],
    });
  });

  it("selects an available model when DeepSeek is hidden", () => {
    const option: SessionConfigOption = {
      type: "select",
      id: "model",
      name: "Model",
      currentValue: "deepseek-ai/deepseek-v4-flash-0731",
      options: [
        {
          value: "deepseek-ai/deepseek-v4-flash-0731",
          name: "DeepSeek V4 Flash",
        },
        { value: "claude-opus-4-8", name: "Claude Opus 4.8" },
      ],
    };

    expect(stripDeepseekModelOption(option)).toMatchObject({
      currentValue: "claude-opus-4-8",
      options: [{ value: "claude-opus-4-8" }],
    });
  });
});
