import { describe, expect, it } from "vitest";
import { parseWindowListPlist } from "./cg-window-list";

/**
 * A binary plist shaped like a real `CGWindowListCopyWindowInfo` result: a
 * Dock-owned Mission Control backing window, an app window, and a system
 * surface with no owner name. Regenerate with:
 *
 *   python3 -c "import plistlib,base64; print(base64.b64encode(
 *     plistlib.dumps([...], fmt=plistlib.FMT_BINARY)).decode())"
 */
const WINDOW_LIST_PLIST = Buffer.from(
  "YnBsaXN0MDCjARQc1QIDBAUGBxAREhNfEA9rQ0dXaW5kb3dCb3VuZHNfEBNrQ0dXaW5kb3dJc09uc2NyZWVuXmtDR1dpbmRvd0xheWVyXxAPa0NHV2luZG93TnVtYmVyXxASa0NHV2luZG93T3duZXJOYW1l1AgJCgsMDQ4PVkhlaWdodFVXaWR0aFFYUVkjQIwoAAAAAAAjQJaAAAAAAAAjAAAAAAAAAAAjv/AAAAAAAAAJEBQQe1REb2Nr0wIEBhUaG9QICQoLFhcYGSNAgsAAAAAAACNAiQAAAAAAACNAKAAAAAAAACNAQwAAAAAAABAAV1Bvc3RIb2fSAgQdH9QICQoLHg0ODiNAOAAAAAAAABAZAAgADAAXACkAPwBOAGAAdQB+AIUAiwCNAI8AmAChAKoAswC0ALYAuAC9AMQAzQDWAN8A6ADxAPMA+wEAAQkBEgAAAAAAAAIBAAAAAAAAACAAAAAAAAAAAAAAAAAAAAEU",
  "base64",
);

describe("parseWindowListPlist", () => {
  it("maps CoreGraphics' capitalised bounds keys onto our window type", () => {
    // The whole heuristic keys off bounds.y, so reading X/Y/Width/Height as if
    // they were lowercase would silently report every window at the origin and
    // the overlay would never fire.
    expect(parseWindowListPlist(WINDOW_LIST_PLIST)).toEqual([
      {
        ownerName: "Dock",
        layer: 20,
        bounds: { x: 0, y: -1, width: 1440, height: 901 },
      },
      {
        ownerName: "PostHog",
        layer: 0,
        bounds: { x: 12, y: 38, width: 800, height: 600 },
      },
      {
        // kCGWindowOwnerName is absent for some system surfaces; it must not
        // become the string "undefined" and accidentally match a filter.
        ownerName: "",
        layer: 25,
        bounds: { x: 0, y: 0, width: 1440, height: 24 },
      },
    ]);
  });

  it("returns nothing for a plist that isn't a window array", () => {
    const notAnArray = Buffer.from(
      "YnBsaXN0MDDRAQJTb25lU3R3bwgLDwAAAAAAAAEBAAAAAAAAAAMAAAAAAAAAAAAAAAAAAAAT",
      "base64",
    );

    expect(parseWindowListPlist(notAnArray)).toEqual([]);
  });
});
