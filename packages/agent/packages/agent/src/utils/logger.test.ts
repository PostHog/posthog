import { RequestError } from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

describe("Logger output", () => {
  const spies = {
    debug: vi.spyOn(console, "debug").mockImplementation(() => {}),
    info: vi.spyOn(console, "info").mockImplementation(() => {}),
    warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
    error: vi.spyOn(console, "error").mockImplementation(() => {}),
  };
  const levels = ["debug", "info", "warn", "error"] as const;
  const secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789";

  const written = () =>
    levels.filter((level) => spies[level].mock.calls.length);

  beforeEach(() => {
    for (const spy of Object.values(spies)) spy.mockClear();
  });

  it.each(levels)("json format writes one parseable line for %s", (level) => {
    new Logger({ format: "json", level: "debug", prefix: "[Test]" })[level](
      "hello",
      { a: { b: 1 } },
    );

    expect(spies[level]).toHaveBeenCalledTimes(1);
    const line = spies[level].mock.calls[0][0] as string;
    expect(line).not.toContain("\n");
    expect(JSON.parse(line)).toMatchObject({
      level,
      prefix: "[Test]",
      message: "hello",
      data: { a: { b: 1 } },
    });
  });

  it("json format omits data when none is given", () => {
    new Logger({ format: "json", level: "debug" }).info("hello");

    const parsed = JSON.parse(spies.info.mock.calls[0][0] as string);
    expect(parsed).not.toHaveProperty("data");
  });

  it.each([
    ["debug", ["debug", "info", "warn", "error"]],
    ["info", ["info", "warn", "error"]],
    ["warn", ["warn", "error"]],
    ["error", ["error"]],
  ] as const)("level %s writes only %j", (minLevel, expected) => {
    const logger = new Logger({ level: minLevel });

    for (const level of levels) logger[level]("msg");

    expect(written()).toEqual(expected);
  });

  it.each(levels)("json format redacts secrets for %s", (level) => {
    new Logger({ format: "json", level: "debug" })[level](`token ${secret}`, {
      apiKey: secret,
    });

    expect(spies[level].mock.calls[0][0]).not.toContain(secret);
  });

  it("keeps the default text format", () => {
    new Logger({ debug: true, prefix: "[Test]" }).info("hello", { a: 1 });

    expect(spies.info.mock.calls[0][0]).toMatch(
      /^\S+ \[Test\] \[info\] hello \{\n {2}"a": 1\n\}$/,
    );
  });

  it.each([
    [false, ["error"]],
    [true, ["debug", "info", "warn", "error"]],
  ] as const)("without a level, debug=%s writes %j", (debug, expected) => {
    const logger = new Logger({ debug });

    for (const level of levels) logger[level]("msg");

    expect(written()).toEqual(expected);
  });

  it("child loggers inherit level and format", () => {
    const child = new Logger({
      format: "json",
      level: "warn",
      prefix: "[Test]",
    }).child("kid");

    child.info("hidden");
    child.warn("shown");

    expect(spies.info).not.toHaveBeenCalled();
    expect(JSON.parse(spies.warn.mock.calls[0][0] as string)).toMatchObject({
      prefix: "[Test] [kid]",
      message: "shown",
    });
  });

  it("onLog still takes precedence over format and level", () => {
    const onLog = vi.fn();

    new Logger({ onLog, format: "json", level: "error" }).debug("msg");

    expect(onLog).toHaveBeenCalledWith("debug", "agent", "msg", undefined);
    expect(spies.debug).not.toHaveBeenCalled();
  });
});
