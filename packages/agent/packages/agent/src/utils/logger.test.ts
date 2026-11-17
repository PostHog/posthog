import { RequestError } from "@agentclientprotocol/sdk";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
  const levels = ["debug", "info", "warn", "error"] as const;
  const secret = "ghp_abcdefghijklmnopqrstuvwxyz0123456789";
  const written: { level: string; line: string }[] = [];

  const writtenLevels = () => written.map((entry) => entry.level);

  beforeEach(() => {
    written.length = 0;
    for (const level of levels) {
      vi.spyOn(console, level).mockImplementation((line: string) => {
        written.push({ level, line });
      });
    }
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it.each(levels)("json format writes one parseable line for %s", (level) => {
    new Logger({ format: "json", level: "debug", prefix: "[Test]" })[level](
      "hello",
      { a: { b: 1 } },
    );

    expect(written).toHaveLength(1);
    expect(written[0].level).toBe(level);
    expect(written[0].line).not.toContain("\n");
    expect(JSON.parse(written[0].line)).toMatchObject({
      level,
      prefix: "[Test]",
      message: "hello",
      data: { a: { b: 1 } },
    });
  });

  it("json format omits data when none is given", () => {
    new Logger({ format: "json", level: "debug" }).info("hello");

    expect(JSON.parse(written[0].line)).not.toHaveProperty("data");
  });

  it.each([
    ["debug", ["debug", "info", "warn", "error"]],
    ["info", ["info", "warn", "error"]],
    ["warn", ["warn", "error"]],
    ["error", ["error"]],
  ] as const)("level %s writes only %j", (minLevel, expected) => {
    const logger = new Logger({ level: minLevel });

    for (const level of levels) logger[level]("msg");

    expect(writtenLevels()).toEqual(expected);
  });

  it.each(levels)("json format redacts secrets for %s", (level) => {
    new Logger({ format: "json", level: "debug" })[level](`token ${secret}`, {
      apiKey: secret,
    });

    expect(written[0].line).not.toContain(secret);
  });

  it("keeps the default text format", () => {
    new Logger({ debug: true, prefix: "[Test]" }).info("hello", { a: 1 });

    expect(written[0].line).toMatch(
      /^\S+ \[Test\] \[info\] hello \{\n {2}"a": 1\n\}$/,
    );
  });

  it.each([
    [false, ["error"]],
    [true, ["debug", "info", "warn", "error"]],
  ] as const)("without a level, debug=%s writes %j", (debug, expected) => {
    const logger = new Logger({ debug });

    for (const level of levels) logger[level]("msg");

    expect(writtenLevels()).toEqual(expected);
  });

  it("child loggers inherit level and format", () => {
    const child = new Logger({
      format: "json",
      level: "warn",
      prefix: "[Test]",
    }).child("kid");

    child.info("hidden");
    child.warn("shown");

    expect(written.map((entry) => JSON.parse(entry.line))).toMatchObject([
      { prefix: "[Test] [kid]", message: "shown" },
    ]);
  });

  it("onLog still takes precedence over format and level", () => {
    const received: string[] = [];
    const onLog = (_level: string, _scope: string, message: string) => {
      received.push(message);
    };

    new Logger({ onLog, format: "json", level: "error" }).debug("msg");

    expect(received).toEqual(["msg"]);
    expect(written).toEqual([]);
  });
});
