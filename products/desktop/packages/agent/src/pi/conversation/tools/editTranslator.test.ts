import { describe, expect, it } from "vitest";
import { editTranslator } from "./editTranslator";

describe("editTranslator", () => {
  it("produces a diff from the edit arguments and a location for the path", () => {
    const output = editTranslator({
      toolCallId: "1",
      arguments: {
        path: "src/foo.ts",
        edits: [{ oldText: "const a = 1;", newText: "const a = 2;" }],
      },
      details: {
        diff: "- const a = 1;\n+ const a = 2;",
        patch: "@@ -1 +1 @@\n-const a = 1;\n+const a = 2;",
        firstChangedLine: 3,
      },
    });

    expect(output.locations).toEqual([{ path: "src/foo.ts", line: 3 }]);
    expect(output.content).toEqual([
      {
        type: "diff",
        path: "src/foo.ts",
        oldText: "const a = 1;",
        newText: "const a = 2;",
      },
    ]);
  });

  it("joins multiple edits into a single diff", () => {
    const output = editTranslator({
      toolCallId: "1",
      arguments: {
        path: "src/foo.ts",
        edits: [
          { oldText: "const a = 1;", newText: "const a = 2;" },
          { oldText: "const b = 1;", newText: "const b = 2;" },
        ],
      },
      details: {
        diff: "irrelevant",
        patch: "irrelevant",
      },
    });

    expect(output.content).toEqual([
      {
        type: "diff",
        path: "src/foo.ts",
        oldText: "const a = 1;\nconst b = 1;",
        newText: "const a = 2;\nconst b = 2;",
      },
    ]);
  });

  it("falls back to the details diff string when edits are missing", () => {
    const output = editTranslator({
      toolCallId: "1",
      arguments: { path: "src/foo.ts" },
      details: {
        diff: "- const a = 1;\n+ const a = 2;",
        patch: "@@ -1 +1 @@",
      },
    });

    expect(output.locations).toEqual([{ path: "src/foo.ts", line: undefined }]);
    expect(output.content).toEqual([
      {
        type: "diff",
        path: "src/foo.ts",
        newText: "- const a = 1;\n+ const a = 2;",
      },
    ]);
  });

  it("falls back to result text content on error with no details", () => {
    const output = editTranslator({
      toolCallId: "1",
      arguments: { path: "src/foo.ts" },
      resultContent: [{ type: "text", text: "permission denied" }],
      isError: true,
    });

    expect(output.locations).toEqual([{ path: "src/foo.ts", line: undefined }]);
    expect(output.content).toEqual([
      {
        type: "content",
        content: { type: "text", text: "permission denied" },
      },
    ]);
  });

  it("returns no locations or content when arguments are missing entirely", () => {
    const output = editTranslator({
      toolCallId: "1",
      arguments: undefined,
    });

    expect(output.locations).toBeUndefined();
    expect(output.content).toBeUndefined();
  });
});
