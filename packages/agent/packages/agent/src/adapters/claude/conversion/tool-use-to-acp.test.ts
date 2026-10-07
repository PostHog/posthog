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

  it.each([
    { questionCount: 1, withText: false, title: "Question answered" },
    { questionCount: 2, withText: false, title: "Questions answered" },
    { questionCount: 1, withText: true, title: "Answer received" },
    { questionCount: 2, withText: true, title: "Answers received" },
  ])(
    "titles an AskUserQuestion result for $questionCount question(s) with text=$withText as $title",
    ({ questionCount, withText, title }) => {
      const questions = Array.from({ length: questionCount }, (_, index) => ({
        question: `Question ${index + 1}?`,
        header: `Q${index + 1}`,
        options: [{ label: "Yes" }, { label: "No" }],
      }));

      const result = toolUpdateFromToolResult(
        {
          type: "tool_result",
          tool_use_id: "toolu_1",
          content: withText ? [{ type: "text", text: "Yes" }] : [],
        },
        { name: "AskUserQuestion", input: { questions } },
      );

      expect(result.title).toBe(title);
    },
  );
});
