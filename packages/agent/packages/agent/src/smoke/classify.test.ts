import { describe, expect, it } from "vitest";
import { classifyFailure, classifyOutcome } from "./classify";

describe("smoke classification", () => {
  it.each([
    [
      'API Error: 400 {"type":"error","error":{"message":"thinking.type: disabled is not supported"}}',
      "broken",
    ],
    ["API Error: 404 model not found", "broken"],
    ["unexpected status 401 Unauthorized", "broken"],
    ["API Error: 529 Overloaded", "inconclusive"],
    ["unexpected status 503 Service Unavailable", "inconclusive"],
    ["API Error: 429 rate limit exceeded", "inconclusive"],
    ["turn timed out after 300s", "inconclusive"],
    ["Internal error: API Error: terminated", "inconclusive"],
    ["Internal error: API Error: Connection error.", "inconclusive"],
    [
      "Internal error: The socket connection was closed unexpectedly",
      "inconclusive",
    ],
    ["Internal error: ACP connection closed", "broken"],
    [
      "The agent stopped before completing this request: fetch failed",
      "inconclusive",
    ],
    ["The file contains 500 lines", "broken"],
  ])("classifies the failure %s as %s", (message, expected) => {
    expect(classifyFailure(message)).toBe(expected);
  });

  it.each([
    ["end_turn", 1, true, "nonce", "pass"],
    ["end_turn", 0, true, "nonce", "broken"],
    ["end_turn", 1, false, "rate limit exceeded", "broken"],
    [
      "refusal",
      0,
      false,
      "unexpected status 503 Service Unavailable",
      "inconclusive",
    ],
    ["refusal", 0, false, "unexpected status 401 Unauthorized", "broken"],
  ])(
    "classifies a %s turn with %i tool calls and nonce %s as %5$s",
    (stopReason, completedToolCalls, replyHasNonce, reply, expected) => {
      expect(
        classifyOutcome({
          stopReason,
          completedToolCalls,
          replyHasNonce,
          reply,
        }),
      ).toBe(expected);
    },
  );
});
