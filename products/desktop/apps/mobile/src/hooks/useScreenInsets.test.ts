import { describe, expect, it, vi } from "vitest";

const mockInsets = { top: 47, bottom: 34, left: 0, right: 0 };

vi.mock("react-native-safe-area-context", () => ({
  useSafeAreaInsets: () => mockInsets,
}));

// useMemo just needs to invoke its factory; we don't need a renderer to pin the
// numeric scale, so stub it to call through.
vi.mock("react", async () => {
  const actual = await vi.importActual<typeof import("react")>("react");
  return { ...actual, useMemo: (factory: () => unknown) => factory() };
});

import { BOTTOM_GAP, useScreenInsets } from "./useScreenInsets";

describe("useScreenInsets", () => {
  it("pins the bottom gap scale onto the device inset", () => {
    const { bottom } = useScreenInsets();
    expect(bottom("compact")).toBe(mockInsets.bottom + 12);
    expect(bottom("default")).toBe(mockInsets.bottom + 24);
    expect(bottom("roomy")).toBe(mockInsets.bottom + 40);
    // default variant matches "default"
    expect(bottom()).toBe(bottom("default"));
  });

  it("keeps BOTTOM_GAP values frozen at 12 / 24 / 40", () => {
    expect(BOTTOM_GAP).toEqual({ compact: 12, default: 24, roomy: 40 });
  });

  it("computes the sheet top, fab, and composer offsets", () => {
    const { sheetContentTop, fabBottom, composerBottom } = useScreenInsets();
    expect(sheetContentTop()).toBe(mockInsets.top + 8);
    expect(fabBottom()).toBe(mockInsets.bottom + 20);
    // composer floor is above the inset here, so it tracks the inset
    expect(composerBottom()).toBe(Math.max(mockInsets.bottom, 50));
  });

  it("floors the composer bottom at COMPOSER_MIN_BOTTOM on zero-inset devices", () => {
    mockInsets.bottom = 0;
    const { composerBottom } = useScreenInsets();
    expect(composerBottom()).toBe(50);
    mockInsets.bottom = 34;
  });
});
