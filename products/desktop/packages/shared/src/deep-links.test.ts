import { describe, expect, it } from "vitest";
import {
  buildActionUrl,
  buildInboxDeeplink,
  buildLoopDeeplink,
  buildScoutDeeplink,
  decodePlanBase64,
  getDeeplinkProtocol,
  isPostHogCodeDeeplink,
  type McpAppAction,
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

describe("buildLoopDeeplink", () => {
  it.each<{
    name: string;
    loopId: string;
    isDevBuild: boolean;
    expected: string;
  }>([
    {
      name: "builds a production loop link",
      loopId: "loop-abc-123",
      isDevBuild: false,
      expected: "posthog-code://loop/loop-abc-123",
    },
    {
      name: "uses the dev scheme for dev builds",
      loopId: "loop-abc-123",
      isDevBuild: true,
      expected: "posthog-code-dev://loop/loop-abc-123",
    },
    {
      name: "encodes special characters in the loop id",
      loopId: "id with spaces/&",
      isDevBuild: false,
      expected: "posthog-code://loop/id%20with%20spaces%2F%26",
    },
  ])("$name", ({ loopId, isDevBuild, expected }) => {
    expect(buildLoopDeeplink(loopId, { isDevBuild })).toBe(expected);
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

describe("buildActionUrl", () => {
  const PROD = "posthog-code";
  const DEV = "posthog-code-dev";

  function parse(url: string): {
    protocol: string;
    host: string;
    pathname: string;
    params: URLSearchParams;
  } {
    const parsed = new URL(url);
    return {
      protocol: parsed.protocol,
      host: parsed.host,
      pathname: parsed.pathname,
      params: parsed.searchParams,
    };
  }

  describe("compose", () => {
    it("builds a new-task link with only the prompt when no repo is given", () => {
      expect(
        buildActionUrl({ kind: "compose", prompt: "Fix the login bug" }, PROD),
      ).toBe("posthog-code://new?prompt=Fix%20the%20login%20bug");
    });

    it("appends the repo when one is given", () => {
      expect(
        buildActionUrl(
          {
            kind: "compose",
            prompt: "Fix the login bug",
            repo: "posthog/posthog",
          },
          PROD,
        ),
      ).toBe(
        "posthog-code://new?prompt=Fix%20the%20login%20bug&repo=posthog%2Fposthog",
      );
    });

    it.each<[string, string]>([
      ["ampersand and query separators", "Ship A & B? #now"],
      ["a plus sign", "Bump limit from 1+1 to 3"],
      ["an injected extra parameter", "hi&repo=evil/repo"],
      ["a scheme-looking string", "go to https://evil.example/?x=1#f"],
      ["newlines and quotes", 'Line one\nLine "two"'],
    ])("round-trips a prompt containing %s", (_label, prompt) => {
      const url = buildActionUrl({ kind: "compose", prompt }, PROD);

      const { protocol, host, params } = parse(url as string);
      expect(protocol).toBe("posthog-code:");
      expect(host).toBe("new");
      expect(params.get("prompt")).toBe(prompt);
      expect(params.get("repo")).toBeNull();
    });

    it("round-trips a repo containing characters that need encoding", () => {
      const repo = "posthog/pos hog+1&x";
      const url = buildActionUrl(
        { kind: "compose", prompt: "Do it", repo },
        PROD,
      );

      expect(parse(url as string).params.get("repo")).toBe(repo);
    });

    it("returns null for a blank prompt", () => {
      expect(
        buildActionUrl({ kind: "compose", prompt: "   " }, PROD),
      ).toBeNull();
    });
  });

  describe("open_space", () => {
    it("builds the channel link", () => {
      expect(
        buildActionUrl(
          {
            kind: "open_space",
            channel_id: "019ebc38-d862-77f2-9e56-c5ec42965758",
          },
          PROD,
        ),
      ).toBe("posthog-code://channel/019ebc38-d862-77f2-9e56-c5ec42965758");
    });

    it("percent-encodes the channel id so it cannot add path segments", () => {
      const url = buildActionUrl(
        { kind: "open_space", channel_id: "a/../b?c#d" },
        PROD,
      );

      expect(url).toBe("posthog-code://channel/a%2F..%2Fb%3Fc%23d");
      expect(decodeURIComponent(parse(url as string).pathname.slice(1))).toBe(
        "a/../b?c#d",
      );
    });

    it("returns null for a blank channel id", () => {
      expect(
        buildActionUrl({ kind: "open_space", channel_id: "" }, PROD),
      ).toBeNull();
    });
  });

  describe("open_canvas", () => {
    it("builds the two-segment canvas link", () => {
      expect(
        buildActionUrl(
          {
            kind: "open_canvas",
            channel_id: "019ebc38-d862-77f2-9e56-c5ec42965758",
            canvas_id: "dash_abc123",
          },
          PROD,
        ),
      ).toBe(
        "posthog-code://canvas/019ebc38-d862-77f2-9e56-c5ec42965758/dash_abc123",
      );
    });

    it("percent-encodes both ids so neither can add path segments", () => {
      const url = buildActionUrl(
        {
          kind: "open_canvas",
          channel_id: "chan/1?x",
          canvas_id: "canvas/2#y",
        },
        PROD,
      );

      expect(url).toBe("posthog-code://canvas/chan%2F1%3Fx/canvas%2F2%23y");
      const segments = parse(url as string)
        .pathname.slice(1)
        .split("/");
      expect(segments.map((segment) => decodeURIComponent(segment))).toEqual([
        "chan/1?x",
        "canvas/2#y",
      ]);
    });

    it.each<[string, McpAppAction]>([
      [
        "the canvas id is missing",
        { kind: "open_canvas", channel_id: "chan", canvas_id: "" },
      ],
      [
        "the channel id is missing",
        { kind: "open_canvas", channel_id: "  ", canvas_id: "dash" },
      ],
    ])("returns null rather than a partial link when %s", (_label, action) => {
      expect(buildActionUrl(action, PROD)).toBeNull();
    });
  });

  describe("dev scheme", () => {
    it.each<[string, McpAppAction, string]>([
      [
        "compose",
        { kind: "compose", prompt: "Do it" },
        "posthog-code-dev://new?prompt=Do%20it",
      ],
      [
        "open_space",
        { kind: "open_space", channel_id: "chan" },
        "posthog-code-dev://channel/chan",
      ],
      [
        "open_canvas",
        { kind: "open_canvas", channel_id: "chan", canvas_id: "dash" },
        "posthog-code-dev://canvas/chan/dash",
      ],
    ])("uses the scheme it is given for %s", (_label, action, expected) => {
      expect(buildActionUrl(action, DEV)).toBe(expected);
    });
  });
});
