import { describe, expect, it } from "vitest";
import { writeTranslator } from "./writeTranslator";

describe("writeTranslator", () => {
  it("produces a diff content block and location for the written file", () => {
    const result = writeTranslator({
      toolCallId: "call-1",
      arguments: { path: "src/foo.ts", content: "export const foo = 1;\n" },
    });

    expect(result.locations).toEqual([{ path: "src/foo.ts" }]);
    expect(result.content).toEqual([
      {
        type: "diff",
        path: "src/foo.ts",
        oldText: null,
        newText: "export const foo = 1;\n",
      },
    ]);
  });

  it("still produces a diff when the result is an error", () => {
    const result = writeTranslator({
      toolCallId: "call-2",
      arguments: { path: "src/bar.ts", content: "" },
      isError: true,
      resultContent: [{ type: "text", text: "permission denied" }],
    });

    expect(result.locations).toEqual([{ path: "src/bar.ts" }]);
    expect(result.content).toEqual([
      {
        type: "diff",
        path: "src/bar.ts",
        oldText: null,
        newText: "",
      },
    ]);
  });
});
