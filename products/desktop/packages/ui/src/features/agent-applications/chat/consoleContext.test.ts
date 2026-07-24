import { describe, expect, it } from "vitest";
import {
  buildConsoleContextEnvelope,
  stripConsoleContext,
} from "./consoleContext";

describe("console context envelope", () => {
  it("round-trips: strip removes a prepended envelope", () => {
    const envelope = buildConsoleContextEnvelope({ page: "agent", agent: "x" });
    const wire = `${envelope}\n\nHello there`;
    expect(stripConsoleContext(wire)).toBe("Hello there");
  });

  it("leaves plain text untouched", () => {
    expect(stripConsoleContext("just a message")).toBe("just a message");
  });

  it("only strips a leading envelope, not one mid-message", () => {
    const text =
      "please render [console-context]{}[/console-context] literally";
    expect(stripConsoleContext(text)).toBe(text);
  });

  it("tolerates leading whitespace before the envelope", () => {
    const wire = `  ${buildConsoleContextEnvelope({ page: "agent-list" })}\n\nhi`;
    expect(stripConsoleContext(wire)).toBe("hi");
  });

  it("is a no-op when the closing delimiter is missing", () => {
    const text = "[console-context]{oops";
    expect(stripConsoleContext(text)).toBe(text);
  });
});
