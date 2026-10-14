import type { CommentAnchor } from "@posthog/core/comments/anchors";
import { describe, expect, it } from "vitest";
import {
  type CommentResource,
  commentAgentContext,
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
