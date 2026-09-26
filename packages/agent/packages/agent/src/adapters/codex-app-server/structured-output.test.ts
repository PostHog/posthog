import { describe, expect, it } from "vitest";
import { parseStructuredOutput } from "./structured-output";

describe("parseStructuredOutput", () => {
  it("parses a bare JSON object", () => {
    expect(parseStructuredOutput('{"status": "done"}')).toEqual({
      status: "done",
    });
  });

  it("parses a fenced json code block surrounded by prose", () => {
    const text = 'Here you go:\n```json\n{"status": "done"}\n```\nAll set.';
    expect(parseStructuredOutput(text)).toEqual({ status: "done" });
  });

  it("parses an object embedded in prose", () => {
    const text = 'The result is {"status": "done"} as requested.';
    expect(parseStructuredOutput(text)).toEqual({ status: "done" });
  });

  it("stops at the object's real closing brace despite later braces in prose", () => {
    const text =
      'Result: {"status": "done"} and note that {braces} appear later }';
    expect(parseStructuredOutput(text)).toEqual({ status: "done" });
  });

  it("skips a non-JSON brace group before the real object", () => {
    const text = 'A {rough} answer: {"status": "done"}';
    expect(parseStructuredOutput(text)).toEqual({ status: "done" });
  });

  it("handles braces inside JSON strings", () => {
    const text = 'Answer: {"note": "uses { and } inside"} trailing prose';
    expect(parseStructuredOutput(text)).toEqual({
      note: "uses { and } inside",
    });
  });

  it("returns null for an array, plain prose, or an unclosed object", () => {
    expect(parseStructuredOutput("[1, 2, 3]")).toBeNull();
    expect(parseStructuredOutput("no json here")).toBeNull();
    expect(parseStructuredOutput('leading {"a": 1')).toBeNull();
  });
});
