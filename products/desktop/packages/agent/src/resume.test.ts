import type { ContentBlock } from "@agentclientprotocol/sdk";
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

  it("drops the resume preamble so it can't starve real user turns", () => {
    // A resume preamble embeds the prior summary, so it is one huge user turn.
    // Selecting before filtering it would spend the budget on it and shed the
    // original task statement, which formatConversationForResume later strips.
    const conversation: ConversationTurn[] = [
      {
        role: "user",
        content: [{ type: "text", text: "Original task: do X" }],
      },
      { role: "assistant", content: [{ type: "text", text: "earlier reply" }] },
      {
        role: "user",
        content: [
          {
            type: "text",
            text: `You are resuming a previous conversation. ${"summary ".repeat(30_000)}Continue from where you left off`,
          },
        ],
      },
      { role: "assistant", content: [{ type: "text", text: "resumed reply" }] },
    ];

    const trimmed = trimConversationForSnapshot(conversation);

    const text = (turn: ConversationTurn): string =>
      turn.content
        .filter((b) => b.type === "text")
        .map((b) => (b as { type: "text"; text: string }).text)
        .join("");
    expect(trimmed.some((turn) => text(turn).includes("Original task"))).toBe(
      true,
    );
    expect(
      trimmed.some((turn) => text(turn).includes("You are resuming")),
    ).toBe(false);
  });

  it("caps oversized attachment data but leaves text blocks intact", () => {
    // A single base64 image overruns the byte cap on its own. estimateTurnTokens
    // scores its turn at zero and the tool-only cap never touches turn.content, so
    // without capping here the whole snapshot is skipped for any attachment-carrying
    // task. The resume prompt renders text blocks only, so shedding the image data
    // loses nothing it shows.
    const hugeImage = "A".repeat(3 * 1024 * 1024);
    const conversation: ConversationTurn[] = [
      {
        role: "user",
        content: [
          { type: "text", text: "look at this" },
          {
            type: "image",
            data: hugeImage,
            mimeType: "image/png",
          } as ContentBlock,
        ],
      },
    ];
    expect(serializedBytes(conversation)).toBeGreaterThan(
      RESUME_STATE_MAX_BYTES,
    );

    const trimmed = trimConversationForSnapshot(conversation);

    expect(serializedBytes(trimmed)).toBeLessThan(RESUME_STATE_MAX_BYTES);
    const content = trimmed.at(-1)?.content ?? [];
    expect(content.find((b) => b.type === "text")).toEqual({
      type: "text",
      text: "look at this",
    });
    const image = content.find((b) => b.type === "image") as
      | { data: string }
      | undefined;
    expect(image?.data.length).toBeLessThan(hugeImage.length);
  });
});
