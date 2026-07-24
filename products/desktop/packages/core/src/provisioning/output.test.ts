import { describe, expect, it } from "vitest";
import { appendOutputChunk, stripAnsi } from "./output";

describe("stripAnsi", () => {
  it("removes ANSI color escape sequences", () => {
    expect(stripAnsi("\x1b[31mred\x1b[0m")).toBe("red");
  });

  it("leaves plain text untouched", () => {
    expect(stripAnsi("plain")).toBe("plain");
  });
});

describe("appendOutputChunk", () => {
  it("appends a plain newline-delimited chunk as new lines", () => {
    expect(appendOutputChunk([], "a\nb")).toEqual(["a", "b"]);
  });

  it("continues onto the existing last line when no newline boundary", () => {
    expect(appendOutputChunk(["foo"], "bar")).toEqual(["foobar"]);
  });

  it("overwrites the current line on carriage return", () => {
    expect(appendOutputChunk(["old"], "\rnew")).toEqual(["new"]);
  });

  it("appends a fresh line when carriage return has no prior segment", () => {
    expect(appendOutputChunk([], "\rfresh")).toEqual(["fresh"]);
  });

  it("strips ANSI sequences before processing", () => {
    expect(appendOutputChunk([], "\x1b[32mgreen\x1b[0m")).toEqual(["green"]);
  });

  it("keeps only the last segment after a carriage return overwrite within a part", () => {
    expect(appendOutputChunk([], "first\rsecond")).toEqual(["second"]);
  });
});
