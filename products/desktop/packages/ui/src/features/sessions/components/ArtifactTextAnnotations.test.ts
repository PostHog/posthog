import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  buildTextNodeIndex,
  rangeFromOffsets,
  textHighlightLabel,
} from "./ArtifactTextAnnotations";

describe("ArtifactTextAnnotations", () => {
  it("gives each text highlight its author label", () => {
    const comment = {
      created_by: {
        first_name: "Ada",
        last_name: "Lovelace",
        email: "ada@example.com",
      },
    } as ResourceComment;

    expect(textHighlightLabel(comment)).toBe("Open comment from Ada Lovelace");
  });

  it("resolves several ranges from one text-node index", () => {
    const root = document.createElement("div");
    root.innerHTML = "One <strong>two</strong> three";
    const index = buildTextNodeIndex(root);

    expect(rangeFromOffsets(index, 0, 3)?.toString()).toBe("One");
    expect(rangeFromOffsets(index, 4, 7)?.toString()).toBe("two");
    expect(rangeFromOffsets(index, 8, 13)?.toString()).toBe("three");
  });
});
