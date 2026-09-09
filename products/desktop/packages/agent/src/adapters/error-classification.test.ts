import { describe, expect, it } from "vitest";
import {
  classifyAgentError,
  isPromptTooLongError,
  isRetryableUpstreamErrorClassification,
  sanitizeAgentErrorCause,
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
    ["ACP connection closed", "upstream_connection_error"],
    ["API Error: Request timed out.", "upstream_timeout"],
    ["API Error: 429 rate limited", "upstream_provider_failure"],
    ["API Error: 529 overloaded", "upstream_provider_failure"],
    ["API Error: Content block not found", "content_block_rejection"],
    [
      "API Error: Content block is not a thinking block",
      "content_block_rejection",
    ],
    // The codex app-server reports provider HTTP failures with its own wording.
    [
      "unexpected status 429 Too Many Requests: slow down",
      "upstream_provider_failure",
    ],
    [
      "unexpected status 502 Bad Gateway: upstream unavailable",
      "upstream_provider_failure",
    ],
    ["unexpected status 403 Forbidden: needs a paid plan", "agent_error"],
    [
      "[ede_diagnostic] result_type=user last_content_type=n/a stop_reason=null",
      "turn_ended_without_response",
    ],
    [
      "[ede_diagnostic] result_type=assistant last_content_type=text stop_reason=null",
      "agent_error",
    ],
    [
      "Claude AI usage limit reached. Your limit will reset at 3pm.",
      "subscription_usage_limit",
    ],
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

describe("isRetryableUpstreamErrorClassification", () => {
  it.each([
    ["upstream_stream_terminated", true],
    ["upstream_connection_error", true],
    ["upstream_timeout", true],
    ["upstream_provider_failure", true],
    ["content_block_rejection", false],
    ["turn_ended_without_response", false],
    ["subscription_usage_limit", false],
    ["agent_error", false],
  ] as const)("marks %s as retryable: %s", (classification, expected) => {
    expect(isRetryableUpstreamErrorClassification(classification)).toBe(
      expected,
    );
  });
});

describe("sanitizeAgentErrorCause", () => {
  it.each([
    [
      "unexpected status 503 Service Unavailable: private provider body",
      "upstream_provider_failure",
      "unexpected status 503",
    ],
    [
      "unexpected status 403 Forbidden: private provider body",
      "agent_error",
      "unexpected status 403",
    ],
    [
      "API Error: 529 private provider body",
      "upstream_provider_failure",
      "API Error: 529",
    ],
    [
      "Internal error: API Error: 403 private provider body",
      "agent_error",
      "API Error: 403",
    ],
    [
      "provider request failed without a status",
      "upstream_provider_failure",
      "upstream_provider_failure",
    ],
    [
      "Connection failed: private request details",
      "upstream_connection_error",
      "upstream_connection_error",
    ],
    [
      "Stream terminated after private tool output",
      "upstream_stream_terminated",
      "upstream_stream_terminated",
    ],
    [
      "Request timed out after sending private repository content",
      "upstream_timeout",
      "upstream_timeout",
    ],
    ["agent process exited", "agent_error", "agent process exited"],
  ] as const)("sanitizes %j as %j", (message, classification, expected) => {
    expect(sanitizeAgentErrorCause(message, classification)).toBe(expected);
  });

  it("limits an unclassified cause before persistence", () => {
    const cause = "private response content ".repeat(100);

    expect(sanitizeAgentErrorCause(cause, "agent_error")).toHaveLength(400);
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
