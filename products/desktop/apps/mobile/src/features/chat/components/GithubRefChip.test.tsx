import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import type { PrStatus } from "../../tasks/hooks/usePrStatus";
import { GithubRefChip } from "./GithubRefChip";

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 11: "#444444" },
    status: { success: "#00aa00", error: "#cc0000" },
  }),
  toRgba: (hex: string, alpha: number) => `${hex}/${alpha}`,
  MERGED_COLOR: "#8e4ec6",
}));

vi.mock("@/lib/openExternalUrl", () => ({ openExternalUrl: vi.fn() }));

vi.mock("../../tasks/hooks/usePrStatus", () => ({ usePrStatus: vi.fn() }));

import { usePrStatus } from "../../tasks/hooks/usePrStatus";

const mockUsePrStatus = vi.mocked(usePrStatus);

function setStatus(data: PrStatus | null | undefined) {
  mockUsePrStatus.mockReturnValue({ data } as ReturnType<typeof usePrStatus>);
}

const href = "https://github.com/a/b/pull/1";

function render(props: Parameters<typeof GithubRefChip>[0]) {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(createElement(GithubRefChip, props));
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function chip(renderer: ReturnType<typeof create>): {
  accessibilityLabel: string;
  color: string | undefined;
} {
  const node = renderer.root.findAll(
    (n) => typeof n.props?.onPress === "function",
  )[0];
  return {
    accessibilityLabel: node.props.accessibilityLabel as string,
    color: (node.props.style as { color?: string } | undefined)?.color,
  };
}

const base: PrStatus = {
  state: "open",
  merged: false,
  draft: false,
  additions: 0,
  deletions: 0,
};

describe("GithubRefChip", () => {
  it.each([
    { name: "open", status: { ...base }, color: "#00aa00", state: "open" },
    {
      name: "draft",
      status: { ...base, draft: true },
      color: "#444444",
      state: "draft",
    },
    {
      name: "closed",
      status: { ...base, state: "closed" as const },
      color: "#cc0000",
      state: "closed",
    },
    {
      name: "merged",
      status: { ...base, state: "closed" as const, merged: true },
      color: "#8e4ec6",
      state: "merged",
    },
  ])("tints a $name PR and names its state", ({ status, color, state }) => {
    setStatus(status);
    const { accessibilityLabel, color: rendered } = chip(
      render({ href, kind: "pr", label: "a/b#1" }),
    );
    expect(rendered).toBe(color);
    expect(accessibilityLabel).toBe(`GitHub pull request a/b#1, ${state}`);
  });

  it.each([
    { name: "loading", data: undefined },
    { name: "unresolved (private/404/non-GitHub)", data: null },
  ])("falls back to a neutral, untinted PR chip when $name", ({ data }) => {
    setStatus(data);
    const { accessibilityLabel, color } = chip(
      render({ href, kind: "pr", label: "a/b#1" }),
    );
    expect(color).toBeUndefined();
    expect(accessibilityLabel).toBe("GitHub pull request a/b#1");
  });

  it("renders an issue as a neutral chip without fetching status", () => {
    const { accessibilityLabel, color } = chip(
      render({
        href: "https://github.com/a/b/issues/1",
        kind: "issue",
        label: "a/b#1",
      }),
    );
    expect(color).toBeUndefined();
    expect(accessibilityLabel).toBe("GitHub issue a/b#1");
    expect(mockUsePrStatus).not.toHaveBeenCalled();
  });
});
