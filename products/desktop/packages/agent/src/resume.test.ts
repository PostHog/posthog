import { describe, expect, it } from "vitest";
import { RESUME_STATE_MAX_BYTES } from "./posthog-api";
import { type ConversationTurn, trimConversationForSnapshot } from "./resume";

describe("trimConversationForSnapshot", () => {
  const exchange = (id: number, resultChars: number): ConversationTurn[] => [
    { role: "user", content: [{ type: "text", text: `ask ${id}` }] },
    {
      role: "assistant",
      content: [{ type: "text", text: `answer ${id}` }],
      toolCalls: [
        {
          toolCallId: `call-${id}`,
          toolName: "Read",
          input: { file: `file-${id}.ts` },
          result: "x".repeat(resultChars),
        },
      ],
    },
  ];

  const serializedBytes = (value: unknown): number =>
    Buffer.byteLength(JSON.stringify(value), "utf8");

  it("bounds a long conversation under the stored size limit", () => {
    // Enough exchanges that capping payloads alone still overruns the limit, so
    // this fails if the recent-window selection is dropped.
    const conversation = Array.from({ length: 400 }, (_, index) =>
      exchange(index, 50_000),
    ).flat();
    expect(serializedBytes(conversation)).toBeGreaterThan(
      RESUME_STATE_MAX_BYTES,
    );

    const trimmed = trimConversationForSnapshot(conversation);

    expect(trimmed.length).toBeGreaterThan(0);
    expect(serializedBytes(trimmed)).toBeLessThan(RESUME_STATE_MAX_BYTES);
  });

  it("truncates an oversized tool result instead of shedding it", () => {
    const conversation = exchange(1, 5_000_000);

    const trimmed = trimConversationForSnapshot(conversation);

    // Selecting before capping would send this turn down the oversized-tail
    // fallback, which drops the tool call outright and loses the result.
    expect(trimmed.at(-1)?.toolCalls?.[0]?.result).toBeDefined();
    expect(serializedBytes(trimmed)).toBeLessThan(RESUME_STATE_MAX_BYTES);
  });
});
