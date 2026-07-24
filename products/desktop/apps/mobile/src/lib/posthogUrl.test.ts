import { describe, expect, it } from "vitest";
import { parsePostHogUrl } from "./posthogUrl";

describe("parsePostHogUrl", () => {
  it("parses docs links into compact docs labels", () => {
    expect(parsePostHogUrl("https://posthog.com/docs/session-replay")).toEqual({
      kind: "docs",
      defaultLabel: "Docs / Session replay",
      normalizedUrl: "https://posthog.com/docs/session-replay",
      refId: null,
    });
  });

  it("parses PostHog task run links", () => {
    expect(
      parsePostHogUrl("https://code.posthog.com/task/task-123/run/run-456"),
    ).toEqual({
      kind: "code",
      defaultLabel: "Code / Task run (run-456)",
      normalizedUrl: "https://code.posthog.com/task/task-123/run/run-456",
      refId: "run-456",
    });
  });

  it("parses project feature flag links", () => {
    expect(
      parsePostHogUrl("https://us.posthog.com/project/7/feature_flags/42"),
    ).toEqual({
      kind: "app",
      defaultLabel: "Feature flag (42)",
      normalizedUrl: "https://us.posthog.com/project/7/feature_flags/42",
      refId: "42",
    });
  });

  it("parses relative insight paths using the signed-in app host", () => {
    expect(
      parsePostHogUrl("/insights/UiFKIsO3", {
        appBaseUrl: "https://us.posthog.com",
      }),
    ).toEqual({
      kind: "app",
      defaultLabel: "Insight (UiFKIsO3)",
      normalizedUrl: "https://us.posthog.com/insights/UiFKIsO3",
      refId: "UiFKIsO3",
    });
  });

  it("parses relative PostHog paths using the code host", () => {
    expect(
      parsePostHogUrl("/task/task-123/run/run-456", {
        codeBaseUrl: "https://code.posthog.com",
      }),
    ).toEqual({
      kind: "code",
      defaultLabel: "Code / Task run (run-456)",
      normalizedUrl: "https://code.posthog.com/task/task-123/run/run-456",
      refId: "run-456",
    });
  });

  it("uses the feature flag search query when present", () => {
    expect(
      parsePostHogUrl(
        "https://eu.posthog.com/project/1/feature_flags?search=checkout-redesign",
      ),
    ).toEqual({
      kind: "app",
      defaultLabel: "Feature flags / checkout-redesign",
      normalizedUrl:
        "https://eu.posthog.com/project/1/feature_flags?search=checkout-redesign",
      refId: null,
    });
  });

  it("falls back to generic website labels for non-docs pages", () => {
    expect(parsePostHogUrl("https://posthog.com/pricing")).toEqual({
      kind: "website",
      defaultLabel: "PostHog / Pricing",
      normalizedUrl: "https://posthog.com/pricing",
      refId: null,
    });
  });

  it("ignores non-PostHog links", () => {
    expect(parsePostHogUrl("https://example.com/docs/session-replay")).toBe(
      null,
    );
  });
});
