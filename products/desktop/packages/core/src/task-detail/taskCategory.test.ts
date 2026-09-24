import type { DecisionResponse } from "@posthog/api-client/posthog-client";
import { describe, expect, it, vi } from "vitest";
import { classifyTaskCategory } from "./taskCategory";

function answer(choice: string | null): DecisionResponse {
  return {
    model: "decision-4b",
    answers: {
      category: {
        type: "choice",
        probability: null,
        choice,
        score: null,
        confidence: 0.9,
        probabilities: null,
      },
    },
    input_tokens: 12,
    latency_ms: 40,
  };
}

describe("classifyTaskCategory", () => {
  it.each([
    ["a known choice", async () => answer("perf"), "perf"],
    ["a choice outside the list", async () => answer("wip"), null],
    ["no choice", async () => answer(null), null],
    [
      "a failed request",
      async () => {
        throw new Error("Decision request failed: 404");
      },
      null,
    ],
  ])("resolves %s", async (_name, decide, expected) => {
    const client = { decide: vi.fn(decide) };

    await expect(
      classifyTaskCategory(client, "  The dashboard loads slowly\n"),
    ).resolves.toBe(expected);
    expect(client.decide).toHaveBeenCalledWith(
      expect.objectContaining({ state: "The dashboard loads slowly" }),
    );
  });

  it("skips the request for an empty prompt", async () => {
    const client = { decide: vi.fn() };

    await expect(classifyTaskCategory(client, "   ")).resolves.toBeNull();
    expect(client.decide).not.toHaveBeenCalled();
  });

  it("gives up when the model does not answer in time", async () => {
    vi.useFakeTimers();
    try {
      const client = {
        decide: vi.fn(
          ({ signal }: { signal?: AbortSignal }) =>
            new Promise<DecisionResponse>((_resolve, reject) => {
              signal?.addEventListener("abort", () =>
                reject(new Error("aborted")),
              );
            }),
        ),
      };

      const pending = classifyTaskCategory(client, "Add dark mode", 1_000);
      await vi.advanceTimersByTimeAsync(1_000);

      await expect(pending).resolves.toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});
