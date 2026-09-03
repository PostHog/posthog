import { describe, expect, it } from "vitest";
import { toolUpdateFromToolResult } from "./tool-use-to-acp";

describe("toolUpdateFromToolResult", () => {
  it("does not forward document bytes from Read results", () => {
    const pdfData = "base64-pdf-data";
    const result = toolUpdateFromToolResult(
      {
        type: "tool_result",
        tool_use_id: "toolu_1",
        content: [
          {
            type: "document",
            source: {
              type: "base64",
              media_type: "application/pdf",
              data: pdfData,
            },
          },
        ],
      } as never,
      { name: "Read", input: {} },
    );

    expect(result.content).toEqual([
      {
        type: "content",
        content: {
          type: "text",
          text: "Document content omitted from session updates.",
        },
      },
    ]);
    expect(JSON.stringify(result)).not.toContain(pdfData);
  });
});
