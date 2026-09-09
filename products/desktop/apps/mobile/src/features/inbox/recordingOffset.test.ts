import { describe, expect, it } from "vitest";
import {
  colonOffsetFromSeconds,
  colonOffsetToSeconds,
} from "./recordingOffset";

describe("colonOffsetToSeconds", () => {
  it.each([
    ["MM:SS", "01:47", 107],
    ["HH:MM:SS", "1:02:03", 3723],
    ["zero-padded minutes", "10:00", 600],
  ])("parses %s", (_label, offset, expected) => {
    expect(colonOffsetToSeconds(offset)).toBe(expected);
  });

  it.each([
    ["a bare number", "47"],
    ["too many parts", "1:2:3:4"],
    ["a non-numeric part", "ab:cd"],
    ["a negative part", "-1:00"],
    ["an empty segment", "1::2"],
    ["a hex literal", "0x10:00"],
    ["scientific notation", "1e308:00"],
    ["padded whitespace", " 1 : 2 "],
    ["seconds of 60", "1:60"],
    ["minutes of 60 in HH:MM:SS", "1:60:00"],
  ])("returns null for %s", (_label, offset) => {
    expect(colonOffsetToSeconds(offset)).toBeNull();
  });
});

describe("colonOffsetFromSeconds", () => {
  it.each([
    ["under an hour", 107, "01:47"],
    ["exactly zero", 0, "00:00"],
    ["over an hour", 3723, "01:02:03"],
    ["rounding fractional seconds", 30.4, "00:30"],
    ["clamping negatives to zero", -5, "00:00"],
  ])("formats %s", (_label, seconds, expected) => {
    expect(colonOffsetFromSeconds(seconds)).toBe(expected);
  });
});
