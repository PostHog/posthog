import type { EditorContent } from "@posthog/core/message-editor/content";
import { describe, expect, it } from "vitest";
import { buildEvidenceComposerContent } from "./evidenceComposer";

describe("buildEvidenceComposerContent", () => {
  it.each([
    [null, "Ask about "],
    [
      { segments: [{ type: "text", text: "Compare the variants" }] },
      "\n\nAsk about ",
    ],
  ] as const)(
    "preserves the current draft boundary",
    (currentDraft, prefix) => {
      expect(
        buildEvidenceComposerContent({
          kind: "insight",
          id: "9pQx3",
          label: "Insight: Checkout funnel",
          currentDraft: currentDraft as EditorContent | null,
        }),
      ).toEqual({
        segments: [
          { type: "text", text: prefix },
          {
            type: "chip",
            chip: {
              type: "posthog_object",
              objectKind: "insight",
              id: "9pQx3",
              label: "Insight: Checkout funnel",
            },
          },
          { type: "text", text: " " },
        ],
      });
    },
  );
});
