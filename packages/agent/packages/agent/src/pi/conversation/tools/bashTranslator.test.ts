import { describe, expect, it } from "vitest";
import { bashTranslator } from "./bashTranslator";

describe("bashTranslator", () => {
  it("surfaces command output as text content on success", () => {
    const result = bashTranslator({
      toolCallId: "tool-1",
      arguments: { command: "echo hi" },
      resultContent: [{ type: "text", text: "hi\n" }],
      details: { truncation: undefined, fullOutputPath: undefined },
      isError: false,
    });

    expect(result).toEqual({
      content: [
        {
          type: "content",
          content: { type: "text", text: "hi\n" },
        },
      ],
    });
  });

  it("surfaces stderr-style output for a failed command", () => {
    const result = bashTranslator({
      toolCallId: "tool-2",
      arguments: { command: "false" },
      resultContent: [
        { type: "text", text: "command failed with exit code 1" },
      ],
      isError: true,
    });

    expect(result).toEqual({
      content: [
        {
          type: "content",
          content: { type: "text", text: "command failed with exit code 1" },
        },
      ],
    });
  });

  it("returns no content when the result has no text blocks", () => {
    const result = bashTranslator({
      toolCallId: "tool-3",
      arguments: { command: "echo hi" },
      resultContent: [],
    });

    expect(result).toEqual({});
  });

  it("joins multiple text blocks and ignores image blocks", () => {
    const result = bashTranslator({
      toolCallId: "tool-4",
      arguments: { command: "cat file.txt" },
      resultContent: [
        { type: "text", text: "line one\n" },
        { type: "image", data: "abc", mimeType: "image/png" },
        { type: "text", text: "line two\n" },
      ],
    });

    expect(result).toEqual({
      content: [
        {
          type: "content",
          content: { type: "text", text: "line one\nline two\n" },
        },
      ],
    });
  });

  it("returns no content when resultContent is missing", () => {
    const result = bashTranslator({
      toolCallId: "tool-5",
      arguments: { command: "echo hi" },
    });

    expect(result).toEqual({});
  });
});
