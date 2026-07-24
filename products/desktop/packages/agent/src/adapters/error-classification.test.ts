import { describe, expect, it } from "vitest";
import { classifyAgentError } from "./error-classification";

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
