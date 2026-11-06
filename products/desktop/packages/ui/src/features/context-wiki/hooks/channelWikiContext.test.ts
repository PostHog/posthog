import { describe, expect, it, vi } from "vitest";

// The real client pulls in @posthog/shared, which this package's vitest config
// does not resolve; only the 403 marker class matters here.
vi.mock("@posthog/api-client/posthog-client", () => ({
  ContextWikiUnavailableError: class ContextWikiUnavailableError extends Error {},
}));

const { ContextWikiUnavailableError } = await import(
  "@posthog/api-client/posthog-client"
);
const { channelWikiContextFrom } = await import("./useContextWiki");

const page = { path: "channels/growth.md" };

describe("channelWikiContextFrom", () => {
  it.each([
    // A task must never be submitted with the space context silently gone, so a
    // failure that a retry could fix has to hold submission...
    [
      "a transient failure",
      {
        enabled: true,
        data: undefined,
        error: new Error("500"),
        isLoading: false,
      },
      { blocked: true, failed: true, unavailable: false, useLegacy: false },
    ],
    // ...while the 403 never clears, so holding there would lock every space in
    // a private-project organization out of creating tasks at all.
    [
      "a permanent 403",
      {
        enabled: true,
        data: undefined,
        error: new ContextWikiUnavailableError("private projects"),
        isLoading: false,
      },
      { blocked: false, failed: false, unavailable: true, useLegacy: false },
    ],
    [
      "a lookup still in flight",
      { enabled: true, data: undefined, error: null, isLoading: true },
      { blocked: true, failed: false, unavailable: false, useLegacy: false },
    ],
    [
      "a resolved page",
      { enabled: true, data: page, error: null, isLoading: false },
      { blocked: false, failed: false, unavailable: false, useLegacy: false },
    ],
    [
      "a space with no wiki page",
      { enabled: true, data: null, error: null, isLoading: false },
      { blocked: false, failed: false, unavailable: false, useLegacy: true },
    ],
    [
      "the flag being off",
      { enabled: false, data: undefined, error: null, isLoading: false },
      { blocked: false, failed: false, unavailable: false, useLegacy: true },
    ],
  ])("decides what to do about %s", (_label, lookup, expected) => {
    expect(channelWikiContextFrom(lookup)).toMatchObject(expected);
  });

  it("passes the resolved page path through, and nothing otherwise", () => {
    expect(
      channelWikiContextFrom({
        enabled: true,
        data: page,
        error: null,
        isLoading: false,
      }).path,
    ).toBe("channels/growth.md");
    expect(
      channelWikiContextFrom({
        enabled: true,
        data: null,
        error: null,
        isLoading: false,
      }).path,
    ).toBeUndefined();
  });
});
