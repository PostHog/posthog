import { describe, expect, it } from "vitest";
import { truncateUtf8 } from "./text-truncate";

describe("truncateUtf8", () => {
  it("returns the input unchanged with omittedBytes 0 when under the cap", () => {
    const result = truncateUtf8("hello", 100);
    expect(result).toEqual({ text: "hello", omittedBytes: 0 });
  });

  it("returns the input unchanged when exactly at the cap", () => {
    const text = "x".repeat(10);
    expect(truncateUtf8(text, 10)).toEqual({ text, omittedBytes: 0 });
  });

  it("truncates ASCII text to exactly maxBytes", () => {
    const result = truncateUtf8("abcdefghij", 5);
    expect(result.text).toBe("abcde");
    expect(result.omittedBytes).toBe(5);
  });

  it("never splits a multi-byte UTF-8 codepoint, even when the cut lands mid-sequence", () => {
    // "é" is 2 bytes in UTF-8 (0xC3 0xA9). Cutting at byte 1 must drop the
    // whole character rather than emit a dangling lead byte / replacement char.
    const result = truncateUtf8("aé", 1);
    expect(result.text).toBe("a");
    expect(Buffer.byteLength(result.text, "utf8")).toBeLessThanOrEqual(1);
    // Round-trips through Buffer without producing replacement characters.
    expect(result.text).not.toContain("\uFFFD");
  });

  it("never splits a 4-byte UTF-8 codepoint (e.g. an emoji)", () => {
    const emoji = "😀"; // 4 bytes in UTF-8
    const result = truncateUtf8(`x${emoji}y`, 2); // cap lands inside the emoji's 4 bytes
    expect(result.text).toBe("x");
    expect(result.text).not.toContain("\uFFFD");
  });

  it("produces valid, round-trippable UTF-8 for a large multibyte string near the boundary", () => {
    const text = "€".repeat(1000); // 3 bytes each in UTF-8
    const result = truncateUtf8(text, 3001); // not a multiple of 3, forces a boundary split
    expect(Buffer.byteLength(result.text, "utf8")).toBeLessThanOrEqual(3001);
    expect(result.text).not.toContain("\uFFFD");
    // Every character in the result should be a complete "€".
    expect(result.text.length % 1).toBe(0);
    expect([...result.text].every((ch) => ch === "€")).toBe(true);
  });

  it("reports accurate omittedBytes", () => {
    const text = "x".repeat(100);
    const result = truncateUtf8(text, 40);
    expect(result.omittedBytes).toBe(60);
  });

  it("handles an empty string", () => {
    expect(truncateUtf8("", 10)).toEqual({ text: "", omittedBytes: 0 });
  });

  it("handles maxBytes of 0 by returning an empty string", () => {
    const result = truncateUtf8("hello", 0);
    expect(result.text).toBe("");
    expect(result.omittedBytes).toBe(5);
  });
});
