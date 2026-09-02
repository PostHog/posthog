import { describe, expect, it } from "vitest";
import { detectRepoFullName, isRepoMismatch } from "./repoMismatch";

describe("detectRepoFullName", () => {
  it("is null when nothing detected", () => {
    expect(detectRepoFullName(null)).toBe(null);
  });

  it("joins organization and repository", () => {
    expect(
      detectRepoFullName({ organization: "PostHog", repository: "posthog" }),
    ).toBe("PostHog/posthog");
  });
});

describe("isRepoMismatch", () => {
  it("is false when linked repo is null", () => {
    expect(isRepoMismatch(null, "PostHog/posthog")).toBe(false);
  });

  it("is false when detected full name is null", () => {
    expect(isRepoMismatch("PostHog/posthog", null)).toBe(false);
  });

  it("is false when names match exactly", () => {
    expect(isRepoMismatch("PostHog/posthog", "PostHog/posthog")).toBe(false);
  });

  it("is false when names match case-insensitively", () => {
    expect(isRepoMismatch("PostHog/posthog", "posthog/POSTHOG")).toBe(false);
  });

  it("is true when names differ", () => {
    expect(isRepoMismatch("PostHog/posthog", "PostHog/other")).toBe(true);
  });
});
