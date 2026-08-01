import { describe, expect, it } from "vitest";
import {
  buildInboxDeeplink,
  buildScoutDeeplink,
  decodePlanBase64,
  getDeeplinkProtocol,
  isPostHogCodeDeeplink,
  parseGitHubIssueUrl,
} from "./deep-links";

describe("getDeeplinkProtocol", () => {
  it("returns the dev or production scheme", () => {
    expect(getDeeplinkProtocol(true)).toBe("posthog-code-dev");
    expect(getDeeplinkProtocol(false)).toBe("posthog-code");
  });
});

describe("isPostHogCodeDeeplink", () => {
  it("recognizes production and dev schemes", () => {
    expect(isPostHogCodeDeeplink("posthog-code://task/1")).toBe(true);
    expect(isPostHogCodeDeeplink("posthog-code-dev://task/1")).toBe(true);
  });

  it("rejects other schemes and undefined", () => {
    expect(isPostHogCodeDeeplink("https://example.com")).toBe(false);
    expect(isPostHogCodeDeeplink(undefined)).toBe(false);
    expect(isPostHogCodeDeeplink("not a url")).toBe(false);
  });
});

describe("buildInboxDeeplink", () => {
  it("returns just the UUID when no title is given", () => {
    expect(buildInboxDeeplink("abc-123", null, { isDevBuild: false })).toBe(
      "posthog-code://inbox/abc-123",
    );
    expect(
      buildInboxDeeplink("abc-123", undefined, { isDevBuild: false }),
    ).toBe("posthog-code://inbox/abc-123");
    expect(buildInboxDeeplink("abc-123", "", { isDevBuild: false })).toBe(
      "posthog-code://inbox/abc-123",
    );
  });

  it("emits `--` for runs that mix a colon with other unsafe chars", () => {
    expect(
      buildInboxDeeplink("abc-123", "fix(inbox): Add foo", {
        isDevBuild: false,
      }),
    ).toBe("posthog-code://inbox/abc-123/fix-inbox--Add-foo");
  });

  it("emits a single `-` for a colon-only run", () => {
    expect(
      buildInboxDeeplink("abc-123", "feat:bar", { isDevBuild: false }),
    ).toBe("posthog-code://inbox/abc-123/feat-bar");
  });

  it("omits the slug when the title slugifies to empty", () => {
    expect(buildInboxDeeplink("abc-123", ":::", { isDevBuild: false })).toBe(
      "posthog-code://inbox/abc-123",
    );
    expect(buildInboxDeeplink("abc-123", "   ", { isDevBuild: false })).toBe(
      "posthog-code://inbox/abc-123",
    );
  });

  it("uses the dev scheme when isDevBuild is true", () => {
    expect(
      buildInboxDeeplink("abc-123", "Hello World", { isDevBuild: true }),
    ).toBe("posthog-code-dev://inbox/abc-123/Hello-World");
  });

  it("preserves URL-unreserved punctuation (- _ . ~)", () => {
    expect(
      buildInboxDeeplink("abc-123", "v1.2.3_final~ish", { isDevBuild: false }),
    ).toBe("posthog-code://inbox/abc-123/v1.2.3_final~ish");
  });

  it("collapses runs of unsafe punctuation into a single hyphen", () => {
    expect(
      buildInboxDeeplink("abc-123", "Cost $5, 50% off!", { isDevBuild: false }),
    ).toBe("posthog-code://inbox/abc-123/Cost-5-50-off");
  });

  it("folds accented Latin letters to their ASCII base", () => {
    expect(
      buildInboxDeeplink("abc-123", "café résumé naïve", { isDevBuild: false }),
    ).toBe("posthog-code://inbox/abc-123/cafe-resume-naive");
  });

  it("hyphenizes non-Latin scripts that have no ASCII fold", () => {
    expect(
      buildInboxDeeplink("abc-123", "Hello Привет world", {
        isDevBuild: false,
      }),
    ).toBe("posthog-code://inbox/abc-123/Hello-world");
  });
});

describe("buildScoutDeeplink", () => {
  it.each<{
    name: string;
    skillName: string;
    findingId: string | null | undefined;
    isDevBuild: boolean;
    expected: string;
  }>([
    {
      name: "builds a bare scout link when finding is null",
      skillName: "error-tracking",
      findingId: null,
      isDevBuild: false,
      expected: "posthog-code://scout/error-tracking",
    },
    {
      name: "builds a bare scout link when finding is undefined",
      skillName: "error-tracking",
      findingId: undefined,
      isDevBuild: false,
      expected: "posthog-code://scout/error-tracking",
    },
    {
      name: "appends the finding id as a query param",
      skillName: "error-tracking",
      findingId: "abc-123",
      isDevBuild: false,
      expected: "posthog-code://scout/error-tracking?finding=abc-123",
    },
    {
      name: "strips the signals-scout- prefix from a full skill name",
      skillName: "signals-scout-error-tracking",
      findingId: "f-1",
      isDevBuild: false,
      expected: "posthog-code://scout/error-tracking?finding=f-1",
    },
    {
      name: "uses the dev scheme for dev builds",
      skillName: "web-analytics",
      findingId: null,
      isDevBuild: true,
      expected: "posthog-code-dev://scout/web-analytics",
    },
    {
      name: "encodes special characters in the finding id",
      skillName: "error-tracking",
      findingId: "id with spaces&=",
      isDevBuild: false,
      expected:
        "posthog-code://scout/error-tracking?finding=id%20with%20spaces%26%3D",
    },
  ])("$name", ({ skillName, findingId, isDevBuild, expected }) => {
    expect(buildScoutDeeplink(skillName, findingId, { isDevBuild })).toBe(
      expected,
    );
  });
});

describe("decodePlanBase64", () => {
  it("decodes standard base64", () => {
    const encoded = Buffer.from("hello plan", "utf-8").toString("base64");
    expect(decodePlanBase64(encoded)).toBe("hello plan");
  });

  it("decodes url-safe base64 (- _ and missing padding)", () => {
    const text = "ÿ?ƒplan>>"; // contains chars that produce + / in base64
    const standard = Buffer.from(text, "utf-8").toString("base64");
    const urlSafe = standard
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
    expect(decodePlanBase64(urlSafe)).toBe(text);
  });

  it("returns null for non-base64 input", () => {
    expect(decodePlanBase64("!!!not base64!!!")).toBeNull();
  });
});

describe("parseGitHubIssueUrl", () => {
  it("parses a valid issue URL", () => {
    expect(
      parseGitHubIssueUrl("https://github.com/PostHog/posthog/issues/123"),
    ).toEqual({ owner: "PostHog", repo: "posthog", number: 123 });
  });

  it("rejects non-github hosts", () => {
    expect(parseGitHubIssueUrl("https://gitlab.com/a/b/issues/1")).toBeNull();
  });

  it("rejects non-issue paths", () => {
    expect(parseGitHubIssueUrl("https://github.com/a/b/pull/1")).toBeNull();
  });

  it("rejects a non-positive or non-numeric issue number", () => {
    expect(parseGitHubIssueUrl("https://github.com/a/b/issues/0")).toBeNull();
    expect(parseGitHubIssueUrl("https://github.com/a/b/issues/x")).toBeNull();
  });

  it("returns null for malformed input", () => {
    expect(parseGitHubIssueUrl("not a url")).toBeNull();
  });
});
