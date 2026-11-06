import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type ImageProbe, useImageProbe } from "./useImageProbe";

class FakeImage {
  static instances: FakeImage[] = [];
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  src = "";

  constructor() {
    FakeImage.instances.push(this);
  }
}

const FIRST_URL = "https://example.com/avatar.png";
const RECHECK_URL = "https://example.com/avatar.png?_=2";

describe("useImageProbe", () => {
  beforeEach(() => {
    FakeImage.instances = [];
    vi.stubGlobal("Image", FakeImage);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each<{ name: string; settle: "onload" | "onerror"; expected: ImageProbe }>(
    [
      {
        name: "swaps to the new picture once the re-check loads",
        settle: "onload",
        expected: { result: "loaded", url: RECHECK_URL, loading: false },
      },
      {
        name: "drops the picture when the re-check fails",
        settle: "onerror",
        expected: { result: "failed", url: undefined, loading: false },
      },
    ],
  )(
    "keeps the last picture while re-checking, then $name",
    ({ settle, expected }) => {
      const { result, rerender } = renderHook(({ url }) => useImageProbe(url), {
        initialProps: { url: FIRST_URL },
      });
      act(() => FakeImage.instances[0].onload?.());
      expect(result.current).toEqual({
        result: "loaded",
        url: FIRST_URL,
        loading: false,
      });

      rerender({ url: RECHECK_URL });
      expect(result.current).toEqual({
        result: "loaded",
        url: FIRST_URL,
        loading: true,
      });

      act(() => FakeImage.instances[1][settle]?.());
      expect(result.current).toEqual(expected);
    },
  );
});
