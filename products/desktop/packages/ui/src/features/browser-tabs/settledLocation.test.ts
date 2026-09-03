import { describe, expect, it } from "vitest";
import { settledLocation } from "./settledLocation";

describe("settledLocation", () => {
  // The regression: a tab switch tags the new entry immediately while the
  // navigation is still pending, so `location` says the destination and
  // `resolvedLocation` still says the page being left. Pairing across the two
  // hands the effect "tab B, on tab A's href", which it writes to tab B.
  it("pairs the href and the tab tag from the same snapshot mid-navigation", () => {
    expect(
      settledLocation({
        location: { href: "/spaces/b", state: { tabId: "tab-b" } },
        resolvedLocation: { href: "/spaces/a", state: { tabId: "tab-a" } },
      }),
    ).toEqual({ href: "/spaces/a", tabId: "tab-a", isCurrent: false });
  });

  it("stays pending when only the tab owner changes", () => {
    expect(
      settledLocation({
        location: { href: "/spaces", state: { tabId: "tab-b" } },
        resolvedLocation: { href: "/spaces", state: { tabId: "tab-a" } },
      }),
    ).toEqual({ href: "/spaces", tabId: "tab-a", isCurrent: false });
  });

  it("reads the settled entry once the navigation lands", () => {
    expect(
      settledLocation({
        location: { href: "/spaces/b", state: { tabId: "tab-b" } },
        resolvedLocation: { href: "/spaces/b", state: { tabId: "tab-b" } },
      }),
    ).toEqual({ href: "/spaces/b", tabId: "tab-b", isCurrent: true });
  });

  it("falls back to the location before anything has resolved", () => {
    expect(
      settledLocation({
        location: { href: "/spaces", state: {} },
      }),
    ).toEqual({ href: "/spaces", tabId: null, isCurrent: true });
  });
});
