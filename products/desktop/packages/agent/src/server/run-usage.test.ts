import { describe, expect, test } from "vitest";
import { RunUsageAccumulator } from "./run-usage";

describe("RunUsageAccumulator", () => {
  test("accumulates across turns and defaults nullable ACP fields to 0", () => {
    const acc = new RunUsageAccumulator();

    // Claude-shaped turn: cache components present, no thought tokens.
    expect(
      acc.add({
        inputTokens: 100,
        outputTokens: 50,
        cachedReadTokens: 10,
        cachedWriteTokens: 5,
        totalTokens: 165,
      }),
    ).toBe(true);
    // Codex-shaped turn: null cache writes, reasoning as thought tokens.
    expect(
      acc.add({
        inputTokens: 200,
        outputTokens: 80,
        cachedReadTokens: null,
        cachedWriteTokens: null,
        thoughtTokens: 40,
        totalTokens: 320,
      }),
    ).toBe(true);

    expect(acc.snapshot()).toEqual({
      input_tokens: 300,
      output_tokens: 130,
      cache_read_tokens: 10,
      cache_write_tokens: 5,
      thought_tokens: 40,
      total_tokens: 485,
      turns: 2,
    });
  });

  test.each([[null], [undefined]])(
    "ignores a turn that settles with %s usage",
    (usage) => {
      const acc = new RunUsageAccumulator();
      expect(acc.add(usage)).toBe(false);
      expect(acc.snapshot().turns).toBe(0);
    },
  );

  test("snapshot is a copy — later turns don't mutate earlier snapshots", () => {
    const acc = new RunUsageAccumulator();
    acc.add({ inputTokens: 1, outputTokens: 1, totalTokens: 2 });
    const first = acc.snapshot();
    acc.add({ inputTokens: 1, outputTokens: 1, totalTokens: 2 });
    expect(first.turns).toBe(1);
    expect(acc.snapshot().turns).toBe(2);
  });
});
