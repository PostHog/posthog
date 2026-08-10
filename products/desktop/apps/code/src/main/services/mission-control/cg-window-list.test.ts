import { describe, expect, it } from "vitest";
import { parseWindowListPlist } from "./cg-window-list";

// A CGWindowListCopyWindowInfo-shaped binary plist. Regenerate with:
//   python3 -c "import plistlib,base64; print(base64.b64encode(plistlib.dumps([...], fmt=plistlib.FMT_BINARY)).decode())"
const WINDOW_LIST_PLIST = Buffer.from(
  "YnBsaXN0MDCjARYf1gIDBAUGBwgREhMUFV8QD2tDR1dpbmRvd0JvdW5kc18QE2tDR1dpbmRvd0lzT25zY3JlZW5ea0NHV2luZG93TGF5ZXJfEA9rQ0dXaW5kb3dOdW1iZXJfEBJrQ0dXaW5kb3dPd25lck5hbWVfEBFrQ0dXaW5kb3dPd25lclBJRNQJCgsMDQ4PEFZIZWlnaHRVV2lkdGhRWFFZI0CMKAAAAAAAI0CWgAAAAAAAIwAAAAAAAAAAI7/wAAAAAAAACRAUEHtURG9jaxEBLNQCBAYHFxwdHtQJCgsMGBkaGyNAgsAAAAAAACNAiQAAAAAAACNAKAAAAAAAACNAQwAAAAAAABAAV1Bvc3RIb2cREHLTAgQHICIj1AkKCwwhDg8PI0A4AAAAAAAAEBkRARMACAAMABkAKwBBAFAAYgB3AIsAlACbAKEAowClAK4AtwDAAMkAygDMAM4A0wDWAN8A6ADxAPoBAwEMAQ4BFgEZASABKQEyATQAAAAAAAACAQAAAAAAAAAkAAAAAAAAAAAAAAAAAAABNw==",
  "base64",
);

describe("parseWindowListPlist", () => {
  it("maps CoreGraphics' capitalised bounds keys onto our window type", () => {
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
