import { describe, expect, it } from "vitest";
import { trustedArtifactLink } from "./artifact-preview-link";

describe("trustedArtifactLink", () => {
  it("accepts real link clicks and rejects script-generated clicks", () => {
    const link = document.createElement("a");
    link.href = "https://example.com/report";
    const child = document.createElement("span");
    link.appendChild(child);

    expect(trustedArtifactLink({ isTrusted: true, target: child })).toBe(
      "https://example.com/report",
    );
    expect(trustedArtifactLink({ isTrusted: false, target: child })).toBeNull();
  });
});
