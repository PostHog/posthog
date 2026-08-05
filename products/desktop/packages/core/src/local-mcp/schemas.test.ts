import { describe, expect, it } from "vitest";
import { parseFlaggedMcpServerPayload } from "./schemas";

describe("parseFlaggedMcpServerPayload", () => {
  it("parses a valid payload", () => {
    expect(
      parseFlaggedMcpServerPayload({
        name: "hosthog",
        url: "https://internal.example.test/mcp",
        displayName: "HostHog",
        description: "Internal hosting.",
        iconDomain: "posthog.com",
      }),
    ).toEqual({
      name: "hosthog",
      url: "https://internal.example.test/mcp",
      displayName: "HostHog",
      description: "Internal hosting.",
      iconDomain: "posthog.com",
    });
  });

  it.each([
    { label: "undefined (flag off)", payload: undefined },
    { label: "a non-object payload", payload: "https://example.test/mcp" },
    { label: "a missing url", payload: { name: "hosthog" } },
    {
      label: "a non-http url",
      payload: { name: "hosthog", url: "ftp://example.test/mcp" },
    },
    {
      label: "an unparseable url",
      payload: { name: "hosthog", url: "not a url" },
    },
    {
      label: "a name that is not identifier-shaped",
      payload: { name: "host hog!", url: "https://example.test/mcp" },
    },
  ])("returns null for $label", ({ payload }) => {
    expect(parseFlaggedMcpServerPayload(payload)).toBeNull();
  });
});
