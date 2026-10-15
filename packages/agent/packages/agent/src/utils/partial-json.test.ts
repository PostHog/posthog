import { describe, expect, it } from "vitest";
import { tryParsePartialJson } from "./partial-json";

describe("tryParsePartialJson", () => {
  it("returns null for empty / whitespace input", () => {
    expect(tryParsePartialJson("")).toBeNull();
    expect(tryParsePartialJson("   ")).toBeNull();
  });

  it("parses complete JSON unchanged", () => {
    expect(tryParsePartialJson('{"a":1}')).toEqual({ a: 1 });
    expect(tryParsePartialJson("[1,2,3]")).toEqual([1, 2, 3]);
    expect(tryParsePartialJson('"hello"')).toBe("hello");
  });

  it("closes a single open object", () => {
    expect(tryParsePartialJson("{")).toEqual({});
  });

  it("closes a partial string value and the surrounding object", () => {
    expect(tryParsePartialJson('{"command": "call execute-')).toEqual({
      command: "call execute-",
    });
  });

  it("closes a complete string value with no closing brace", () => {
    expect(tryParsePartialJson('{"command": "tools"')).toEqual({
      command: "tools",
    });
  });

  it("strips a trailing comma after a complete entry", () => {
    expect(tryParsePartialJson('{"a": 1,')).toEqual({ a: 1 });
  });

  it("drops a trailing partial key with no value", () => {
    expect(tryParsePartialJson('{"a": 1, "b":')).toEqual({ a: 1 });
    expect(tryParsePartialJson('{"a": 1, "b"')).toEqual({ a: 1 });
  });

  it("handles nested objects and arrays mid-stream", () => {
    expect(tryParsePartialJson('{"q": {"sql": "SELECT 1')).toEqual({
      q: { sql: "SELECT 1" },
    });
    expect(tryParsePartialJson('{"items": [1, 2, 3')).toEqual({
      items: [1, 2, 3],
    });
  });

  it("respects escaped quotes inside strings", () => {
    expect(tryParsePartialJson('{"q": "say \\"hi\\"')).toEqual({
      q: 'say "hi"',
    });
  });

  it("returns null when nothing parseable can be reconstructed", () => {
    // Garbage that can't be balanced into valid JSON.
    expect(tryParsePartialJson("not json at all")).toBeNull();
  });

  it("parses a typical exec command incrementally", () => {
    // Simulate growth of a streamed { command: "call dashboard-update {...}" }
    expect(tryParsePartialJson('{"command":')).toEqual({});
    expect(tryParsePartialJson('{"command": "ca')).toEqual({ command: "ca" });
    expect(
      tryParsePartialJson('{"command": "call dashboard-update {\\"id\\":'),
    ).toEqual({ command: 'call dashboard-update {"id":' });
    expect(
      tryParsePartialJson('{"command": "call dashboard-update {\\"id\\": 1}"}'),
    ).toEqual({ command: 'call dashboard-update {"id": 1}' });
  });
});
