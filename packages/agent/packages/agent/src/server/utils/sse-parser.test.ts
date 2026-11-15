import { describe, expect, it } from "vitest";
import { SseEventParser } from "./sse-parser";

describe("SseEventParser", () => {
  it("parses complete SSE event", () => {
    const parser = new SseEventParser();
    const events = parser.parse('data: {"message":"hello"}\n\n');

    expect(events).toHaveLength(1);
    expect(events[0].data).toEqual({ message: "hello" });
  });

  it("parses event with id", () => {
    const parser = new SseEventParser();
    const events = parser.parse('id: 123\ndata: {"test":true}\n\n');

    expect(events).toHaveLength(1);
    expect(events[0].id).toBe("123");
    expect(events[0].data).toEqual({ test: true });
  });

  it("handles chunked data", () => {
    const parser = new SseEventParser();

    const events1 = parser.parse("id: 1\n");
    expect(events1).toHaveLength(0);

    const events2 = parser.parse('data: {"part":"one"}');
    expect(events2).toHaveLength(0);

    const events3 = parser.parse("\n\n");
    expect(events3).toHaveLength(1);
    expect(events3[0].id).toBe("1");
    expect(events3[0].data).toEqual({ part: "one" });
  });

  it("parses multiple events in one chunk", () => {
    const parser = new SseEventParser();
    const events = parser.parse('data: {"first":1}\n\ndata: {"second":2}\n\n');

    expect(events).toHaveLength(2);
    expect(events[0].data).toEqual({ first: 1 });
    expect(events[1].data).toEqual({ second: 2 });
  });

  it("skips malformed JSON", () => {
    const parser = new SseEventParser();
    const events = parser.parse('data: not json\n\ndata: {"valid":true}\n\n');

    expect(events).toHaveLength(1);
    expect(events[0].data).toEqual({ valid: true });
  });

  it("handles empty data lines", () => {
    const parser = new SseEventParser();
    const events = parser.parse("data: \n\n");

    expect(events).toHaveLength(0);
  });

  it("resets state correctly", () => {
    const parser = new SseEventParser();

    parser.parse("id: 1\ndata: {");
    parser.reset();

    const events = parser.parse('data: {"fresh":true}\n\n');

    expect(events).toHaveLength(1);
    expect(events[0].id).toBeUndefined();
    expect(events[0].data).toEqual({ fresh: true });
  });

  it("handles events with whitespace in id", () => {
    const parser = new SseEventParser();
    const events = parser.parse('id:   abc123  \ndata: {"test":1}\n\n');

    expect(events).toHaveLength(1);
    expect(events[0].id).toBe("abc123");
  });

  it("preserves incomplete line in buffer", () => {
    const parser = new SseEventParser();

    const events1 = parser.parse('data: {"complete":tr');
    expect(events1).toHaveLength(0);

    const events2 = parser.parse('ue}\n\ndata: {"next":1}\n\n');
    expect(events2).toHaveLength(2);
    expect(events2[0].data).toEqual({ complete: true });
    expect(events2[1].data).toEqual({ next: 1 });
  });
});
