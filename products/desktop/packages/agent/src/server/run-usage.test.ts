import { describe, expect, test, vi } from "vitest";
import type { PostHogAPIClient } from "../posthog-api";
import type { Logger } from "../utils/logger";
import { RunUsageAccumulator, reportRunUsage, seedRunUsage } from "./run-usage";

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

  test("continues stored totals so a same-run resume does not lose them", () => {
    const acc = new RunUsageAccumulator();

    expect(
      seedRunUsage(acc, {
        input_tokens: 100,
        output_tokens: 50,
        cache_read_tokens: 10,
        cache_write_tokens: 5,
        thought_tokens: 0,
        total_tokens: 165,
        turns: 1,
      }),
    ).toBe(true);
    acc.add({
      inputTokens: 200,
      outputTokens: 80,
      totalTokens: 280,
    });

    expect(acc.snapshot()).toEqual({
      input_tokens: 300,
      output_tokens: 130,
      cache_read_tokens: 10,
      cache_write_tokens: 5,
      thought_tokens: 0,
      total_tokens: 445,
      turns: 2,
    });
  });

  test.each([
    ["missing state", undefined],
    ["a non-object value", 42],
  ])("leaves the totals alone when the stored usage is %s", (_label, value) => {
    const acc = new RunUsageAccumulator();
    expect(seedRunUsage(acc, value)).toBe(false);
    expect(acc.snapshot().turns).toBe(0);
  });

  test("does not seed once a turn of its own has been counted", () => {
    const acc = new RunUsageAccumulator();
    acc.add({ inputTokens: 1, outputTokens: 1, totalTokens: 2 });

    expect(
      seedRunUsage(acc, {
        input_tokens: 100,
        output_tokens: 50,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
        thought_tokens: 0,
        total_tokens: 150,
        turns: 1,
      }),
    ).toBe(false);
    expect(acc.snapshot().total_tokens).toBe(2);
  });

  test("snapshot is a copy — later turns don't mutate earlier snapshots", () => {
    const acc = new RunUsageAccumulator();
    acc.add({ inputTokens: 1, outputTokens: 1, totalTokens: 2 });
    const first = acc.snapshot();
    acc.add({ inputTokens: 1, outputTokens: 1, totalTokens: 2 });
    expect(first.turns).toBe(1);
    expect(acc.snapshot().turns).toBe(2);
  });

  test("sends run usage reports one at a time so an older snapshot never lands last", async () => {
    const acc = new RunUsageAccumulator();
    const settle: Array<() => void> = [];
    const updateTaskRun = vi.fn(
      (_taskId: string, _runId: string, body: unknown) =>
        new Promise<unknown>((resolve) => {
          settle.push(() => resolve(body));
        }),
    );
    const api = { updateTaskRun } as unknown as PostHogAPIClient;
    const logger = { warn: vi.fn() } as unknown as Logger;

    acc.add({ inputTokens: 1, outputTokens: 1, totalTokens: 2 });
    const first = reportRunUsage(acc, api, "task-1", "run-1", logger);
    acc.add({ inputTokens: 1, outputTokens: 1, totalTokens: 2 });
    const second = reportRunUsage(acc, api, "task-1", "run-1", logger);

    expect(updateTaskRun).toHaveBeenCalledTimes(1);
    settle[0]();
    await first;
    expect(updateTaskRun).toHaveBeenCalledTimes(2);
    expect(updateTaskRun.mock.calls[1][2]).toEqual({
      state: { token_usage: expect.objectContaining({ turns: 2 }) },
    });
    settle[1]();
    await second;
  });
});
