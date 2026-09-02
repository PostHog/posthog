import { describe, expect, it } from "vitest";
import { trustedArtifactLink } from "./artifact-preview-link";

describe("trustedArtifactLink", () => {
  it("accepts real HTTP link clicks and rejects script-generated clicks", () => {
    const link = document.createElement("a");
    link.href = "https://example.com/report";
    const child = document.createElement("span");
    link.appendChild(child);

    expect(trustedArtifactLink({ isTrusted: true, target: child })).toBe(
      "https://example.com/report",
    );
    expect(trustedArtifactLink({ isTrusted: false, target: child })).toBeNull();
  });

  it.each(["javascript:alert(1)", "file:///etc/passwd", "#section-2"])(
    "rejects non-external link %s",
    (href) => {
      const link = document.createElement("a");
      link.href = href;

      expect(trustedArtifactLink({ isTrusted: true, target: link })).toBeNull();
    },
  );
});
