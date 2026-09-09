import { describe, expect, it } from "vitest";
import { SseEventParser } from "./sse-parser";

describe("SseEventParser", () => {
  it.each([
    [":1234567\n", ":1234567\n", ":1234567\n"],
    ['data: "', "é".repeat(8), "é".repeat(8)],
  ])(
    "bounds a frame across chunks and recovers after rejection",
    (...chunks) => {
      const parser = new SseEventParser(undefined, 24);
      expect(() =>
        chunks.forEach((chunk) => {
          parser.parse(chunk);
        }),
      ).toThrow("SSE frame is too large");
      expect(parser.parse("data: 1\n\n".repeat(10))).toHaveLength(10);
    },
  );

  it("parses event ids and data", () => {
    const parser = new SseEventParser();
    const events = parser.parse('id: 42\ndata: {"hello":"world"}\n\n');

    expect(events).toHaveLength(1);
    expect(events[0]).toEqual({
      event: undefined,
      id: "42",
      data: { hello: "world" },
    });
  });

  it("parses named SSE events", () => {
    const parser = new SseEventParser();
    const events = parser.parse('event: error\ndata: {"error":"boom"}\n\n');

    expect(events).toHaveLength(1);
    expect(events[0].event).toBe("error");
    expect(events[0].data).toEqual({ error: "boom" });
  });

  it("handles chunked input", () => {
    const parser = new SseEventParser();

    expect(parser.parse("id: 1\n")).toEqual([]);
    expect(parser.parse('data: {"part":')).toEqual([]);
    const events = parser.parse("true}\n\n");

    expect(events).toHaveLength(1);
    expect(events[0].id).toBe("1");
    expect(events[0].data).toEqual({ part: true });
  });
});
