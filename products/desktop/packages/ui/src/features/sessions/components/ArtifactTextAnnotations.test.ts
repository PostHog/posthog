import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import { textHighlightLabel } from "./ArtifactTextAnnotations";

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
});
