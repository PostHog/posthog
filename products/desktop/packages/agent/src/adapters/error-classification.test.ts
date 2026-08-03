import { describe, expect, it } from "vitest";
import {
  classifyAgentError,
  isPromptTooLongError,
} from "./error-classification";

describe("classifyAgentError", () => {
  it.each([
    ["API Error: terminated", "upstream_stream_terminated"],
    [
      "API Error: Connection closed mid-response. The response above may be incomplete.",
      "upstream_stream_terminated",
    ],
    [
      "API Error: The socket connection was closed unexpectedly.",
      "upstream_stream_terminated",
    ],
    [
      "The socket connection was closed unexpectedly. For more information, pass `verbose: true`",
      "upstream_stream_terminated",
    ],
    ["socket connection closed", "upstream_stream_terminated"],
    ["API Error: Connection error.", "upstream_connection_error"],
    ["API Error: Request timed out.", "upstream_timeout"],
    ["API Error: 429 rate limited", "upstream_provider_failure"],
    ["API Error: 529 overloaded", "upstream_provider_failure"],
    ["API Error: 400 invalid request", "agent_error"],
    // 413 is a hard client rejection, never a transient upstream failure.
    ["API Error: 413 Payload Too Large", "agent_error"],
    [
      "Connection closed mid-response without the API Error prefix",
      "agent_error",
    ],
    ["some unrelated failure", "agent_error"],
    [undefined, "agent_error"],
  ] as const)("classifies %j as %s", (message, expected) => {
    expect(classifyAgentError(message)).toBe(expected);
  });
});

describe("isPromptTooLongError", () => {
  it.each([
    [
      'API Error: 400 {"type":"error","error":{"type":"invalid_request_error","message":"prompt is too long: 214431 tokens > 204698 maximum"}}',
      true,
    ],
    [
      'API Error: 413 {"error":{"message":"litellm.ContextWindowExceededError: The estimated number of input and maximum output tokens (262334) exceeded this model context window limit (262144)","code":"5021"}}',
      true,
    ],
    // Must match without the "API Error: 413" prefix.
    [
      "litellm.ContextWindowExceededError: The estimated number of input and maximum output tokens (262334) exceeded this model context window limit (262144)",
      true,
    ],
    // The ACP-wrapped shape the agent-server catch actually sees.
    [
      'Internal error: API Error: 413 {"error":{"message":"exceeded this model context window limit (262144)"}}',
      true,
    ],
    // Any gateway 413 means an oversized payload, whatever the body text.
    ["API Error: 413 Payload Too Large", true],
    // Pins the 413 matcher's i flag.
    ["api error: 413 payload too large", true],
    ["API Error: 429 rate limited", false],
    ["API Error: 400 invalid request", false],
    ["some unrelated failure", false],
  ] as const)("detects %j as %s", (message, expected) => {
    expect(isPromptTooLongError(new Error(message))).toBe(expected);
  });

  it("handles non-Error inputs", () => {
    expect(isPromptTooLongError({ message: "prompt is too long" })).toBe(true);
    expect(isPromptTooLongError(undefined)).toBe(false);
  });
});
