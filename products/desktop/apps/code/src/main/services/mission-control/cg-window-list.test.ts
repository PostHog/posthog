import { describe, expect, it } from "vitest";
import {
  createSamplerFromBindings,
  parseWindowListPlist,
  type WindowListBindings,
} from "./cg-window-list";

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

const LIST = { cf: "list" };
const DATA = { cf: "data" };

function fakeBindings(overrides: Partial<WindowListBindings> = {}) {
  const released: unknown[] = [];
  const bindings: WindowListBindings = {
    copyWindowInfo: () => LIST,
    createData: () => DATA,
    getBytePtr: () => null,
    getLength: () => WINDOW_LIST_PLIST.length,
    release: (ref) => released.push(ref),
    decodeBytes: () => new Uint8Array(WINDOW_LIST_PLIST),
    ...overrides,
  };
  return { released, sampler: createSamplerFromBindings(bindings) };
}

describe("createSamplerFromBindings", () => {
  it("parses the window list and releases both owned refs", () => {
    const { released, sampler } = fakeBindings();

    expect(sampler.sample().map((window) => window.ownerName)).toEqual([
      "Dock",
      "PostHog",
      "",
    ]);
    expect(released).toEqual([DATA, LIST]);
  });

  it.each([
    {
      name: "there is no window list",
      overrides: { copyWindowInfo: () => null } as Partial<WindowListBindings>,
      expected: [] as unknown[],
    },
    {
      name: "serialising the plist fails",
      overrides: { createData: () => null } as Partial<WindowListBindings>,
      expected: [LIST] as unknown[],
    },
    {
      name: "the plist data is empty",
      overrides: { getLength: () => 0 } as Partial<WindowListBindings>,
      expected: [DATA, LIST] as unknown[],
    },
  ])(
    "returns nothing and releases only what it owns when $name",
    ({ overrides, expected }) => {
      const { released, sampler } = fakeBindings(overrides);

      expect(sampler.sample()).toEqual([]);
      expect(released).toEqual(expected);
    },
  );

  it("releases both refs even when decoding throws", () => {
    // A skipped CFRelease leaks CoreFoundation objects on every 250ms poll.
    const { released, sampler } = fakeBindings({
      decodeBytes: () => {
        throw new Error("bad pointer");
      },
    });

    expect(() => sampler.sample()).toThrow("bad pointer");
    expect(released).toEqual([DATA, LIST]);
  });
});
