import type { CommentAnchor } from "@posthog/core/comments/anchors";
import { describe, expect, it } from "vitest";
import { parseCommentContextBody } from "../message-editor/components/commentContextBody";
import {
  type CommentResource,
  commentAgentContext,
  commentComposerContent,
} from "./commentAgentContext";

describe("commentAgentContext", () => {
  it.each<{
    name: string;
    anchor: CommentAnchor | null;
    resource: CommentResource;
    label: string | null;
    bodyParts: string[];
  }>([
    {
      name: "a preview element",
      anchor: {
        kind: "element",
        path: "/settings",
        selector: "h1",
        tag: "h1",
        text: "Hot stuff",
        html: "<h1>Hot stuff</h1>",
        attributes: {},
      },
      resource: { kind: "preview", name: "Web app", port: 5173 },
      label: 'h1 "Hot stuff"',
      bodyParts: [
        "- **Page** http://localhost:5173/settings",
        "- **Selector** `h1`",
        "```html\n<h1>Hot stuff</h1>\n```",
      ],
    },
    {
      name: "an artifact quote",
      anchor: {
        kind: "text",
        quote: "Revenue grew\nby 12%",
        prefix: "",
        suffix: "",
        start: 0,
        end: 20,
      },
      resource: { kind: "artifact", name: "report.md" },
      label: 'report.md "Revenue grew by 12%"',
      bodyParts: ["- **Artifact** report.md", "> Revenue grew\n> by 12%"],
    },
    {
      name: "an image region",
      anchor: { kind: "region", x: 0.1, y: 0.2, width: 0.5, height: 0.25 },
      resource: { kind: "artifact", name: "chart.png" },
      label: "chart.png (region)",
      bodyParts: ["- **Region** left 10%, top 20%, width 50%, height 25%"],
    },
    {
      name: "a task comment",
      anchor: { kind: "document" },
      resource: { kind: "task", name: "This task" },
      label: null,
      bodyParts: [],
    },
  ])(
    "describes $name for the agent",
    ({ anchor, resource, label, bodyParts }) => {
      const context = commentAgentContext(anchor, resource);

      expect(context?.label ?? null).toBe(label);
      for (const part of bodyParts) expect(context?.body).toContain(part);
    },
  );
});

describe("commentComposerContent", () => {
  it("puts the context chip before the editable comment", () => {
    expect(
      commentComposerContent({
        comment: "Make this red",
        draftEmpty: false,
        context: { label: 'h1 "Hot stuff"', body: "- **Page** /" },
      }).segments,
    ).toEqual([
      { type: "text", text: "\n" },
      {
        type: "chip",
        chip: {
          type: "comment_context",
          id: "- **Page** /",
          label: 'h1 "Hot stuff"',
        },
      },
      { type: "text", text: " " },
      { type: "text", text: "Make this red" },
    ]);
  });
});
