import { describe, expect, it } from "vitest";
import {
  classifyAgentError,
  isPromptTooLongError,
  isRetryableUpstreamErrorClassification,
  isUpstreamRateLimitFailure,
  parseUpstreamRetryAfterMs,
  sanitizeAgentErrorCause,
  upstreamRetryDelayMs,
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
    [
      "API Error: 429 Rate limit exceeded: This agent run reached its spend limit. Try again in about 24 hours.",
      "task_spend_limit",
    ],
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

describe("isUpstreamRateLimitFailure", () => {
  it.each([
    ["upstream_provider_failure", "API Error: 429", true],
    ["upstream_provider_failure", "unexpected status 429", true],
    ["upstream_provider_failure", "API Error: 503", false],
    ["upstream_provider_failure", "unexpected status 502", false],
    ["upstream_provider_failure", undefined, false],
    // A spend limit also reports 429, and must never earn the longer budget.
    ["task_spend_limit", "API Error: 429", false],
  ] as const)(
    "reads %s / %j as a rate limit: %s",
    (classification, cause, expected) => {
      expect(isUpstreamRateLimitFailure(classification, cause)).toBe(expected);
    },
  );
});

describe("parseUpstreamRetryAfterMs", () => {
  it.each([
    ["Please try again in 1.5s", 1500],
    ["please try again in 20 seconds", 20_000],
    ["Please try again in 2 minutes", 120_000],
    ["Please try again in 400ms", 400],
    ["retry-after: 30", 30_000],
    ["retry-after-ms: 2500", 2500],
    ["API Error: 429 rate limited", null],
    [undefined, null],
  ] as const)("reads %j as %j", (message, expected) => {
    expect(parseUpstreamRetryAfterMs(message)).toBe(expected);
  });
});

describe("upstreamRetryDelayMs", () => {
  // Pinned jitter: 1 takes the top of the window, so these assert the delay
  // itself rather than a range.
  const noJitter = () => 1;

  it.each([
    // A 5xx blip keeps the short delay this loop was tuned for...
    ["API Error: 503", 1, 5_000],
    ["API Error: 503", 2, 10_000],
    // ...while a rate limit starts far higher, grows, and stops at the ceiling
    // that keeps a backed-off turn under the salvage floor.
    ["API Error: 429", 1, 20_000],
    ["unexpected status 429", 2, 40_000],
    ["API Error: 429", 3, 45_000],
    ["API Error: 429", 4, 45_000],
  ] as const)("waits %j retry %i for %ims", (cause, attempt, expected) => {
    expect(
      upstreamRetryDelayMs({
        classification: "upstream_provider_failure",
        attempt,
        cause,
        random: noJitter,
      }),
    ).toBe(expected);
  });

  it.each([
    // The provider knows when its window clears, so a longer hint wins.
    ["upstream_provider_failure", "API Error: 429", "try again in 35s", 35_000],
    // A shorter one would retry while the limit still holds.
    ["upstream_provider_failure", "API Error: 429", "try again in 2s", 20_000],
    // Only a rate limit has a window to wait out.
    ["upstream_timeout", "upstream_timeout", "try again in 40s", 5_000],
  ] as const)(
    "resolves a %s hint %j to %ims",
    (classification, cause, message, expected) => {
      expect(
        upstreamRetryDelayMs({
          classification,
          attempt: 1,
          cause,
          message,
          random: noJitter,
        }),
      ).toBe(expected);
    },
  );

  it("spreads concurrent runs so they do not retry in lockstep", () => {
    const delays = [0, 0.5, 1].map((jitter) =>
      upstreamRetryDelayMs({
        classification: "upstream_provider_failure",
        attempt: 1,
        cause: "API Error: 429",
        random: () => jitter,
      }),
    );

    expect(new Set(delays).size).toBe(3);
    // Every run still waits a useful minimum — half the window at worst.
    expect(Math.min(...delays)).toBe(10_000);
    expect(Math.max(...delays)).toBe(20_000);
  });
});
