import { RequestError } from "@agentclientprotocol/sdk";
import { describe, expect, it, vi } from "vitest";
import { Logger } from "./logger";

describe("Logger.error", () => {
  const circular: Record<string, unknown> = { reason: "loop" };
  circular.self = circular;

  it.each([
    [
      "request error data",
      RequestError.internalError({ details: "Session setup timed out" }),
      { code: -32603, data: { details: "Session setup timed out" } },
    ],
    [
      "circular request error data",
      RequestError.internalError(circular),
      { code: -32603, data: "[object Object]" },
    ],
    ["plain error", new Error("boom"), { message: "boom" }],
  ])("logs %s", (_name, error, expected) => {
    const onLog = vi.fn();

    new Logger({ onLog }).error("failed", error);

    expect(onLog).toHaveBeenCalledWith(
      "error",
      "agent",
      "failed",
      expect.objectContaining(expected),
    );
  });
});
