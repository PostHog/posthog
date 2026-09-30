import { describe, expect, it } from "vitest";
import { shortModelLabel } from "./shortModelLabel";

describe("shortModelLabel drops the vendor word only where a family follows it", () => {
  it.each([
    { label: "Claude Sonnet 5", expected: "Sonnet 5" },
    { label: "Claude Opus 4.8", expected: "Opus 4.8" },
    { label: "Claude Fable 5.1", expected: "Fable 5.1" },
    // A harness, not a model. "Code" alone would name nothing.
    { label: "Claude Code", expected: "Claude Code" },
    { label: "GPT-5.6 Sol", expected: "GPT-5.6 Sol" },
    { label: "GLM-5.3 Flash", expected: "GLM-5.3 Flash" },
    { label: "Kimi K3", expected: "Kimi K3" },
  ])("$label reads as $expected", ({ label, expected }) => {
    expect(shortModelLabel(label)).toBe(expected);
  });
});
