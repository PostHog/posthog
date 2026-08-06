import { describe, expect, it } from "vitest";
import { shouldShowTabBar } from "./panelStoreHelpers";

describe("shouldShowTabBar", () => {
  it.each([
    { name: "chat on its own", tabs: [{ closeable: false }], expected: false },
    {
      name: "chat plus an opened file",
      tabs: [{ closeable: false }, { closeable: true }],
      expected: true,
    },
    {
      name: "a single closeable tab",
      tabs: [{ closeable: true }],
      expected: true,
    },
    { name: "an empty panel", tabs: [], expected: true },
  ])("$name", ({ tabs, expected }) => {
    expect(shouldShowTabBar(tabs)).toBe(expected);
  });
});
