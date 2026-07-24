import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import type { PrStatus } from "../hooks/usePrStatus";
import { PrStatusBadge } from "./PrStatusBadge";

vi.mock("phosphor-react-native", () => ({
  GitMerge: (props: Record<string, unknown>) =>
    createElement("GitMerge", props),
  GitPullRequest: (props: Record<string, unknown>) =>
    createElement("GitPullRequest", props),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 11: "#444444" },
    status: { success: "#00aa00", error: "#cc0000" },
  }),
  toRgba: (hex: string, alpha: number) => `${hex}/${alpha}`,
}));

vi.mock("@/lib/openExternalUrl", () => ({ openExternalUrl: vi.fn() }));

vi.mock("../hooks/usePrStatus", () => ({ usePrStatus: vi.fn() }));

import { usePrStatus } from "../hooks/usePrStatus";

const mockUsePrStatus = vi.mocked(usePrStatus);

function setStatus(data: PrStatus | null | undefined) {
  mockUsePrStatus.mockReturnValue({ data } as ReturnType<typeof usePrStatus>);
}

function render(props: Parameters<typeof PrStatusBadge>[0]) {
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(createElement(PrStatusBadge, props));
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function label(renderer: ReturnType<typeof create>): string | undefined {
  const node = renderer.root.findAll(
    (n) => typeof n.props?.accessibilityLabel === "string",
  )[0];
  return node?.props.accessibilityLabel as string | undefined;
}

function iconCount(renderer: ReturnType<typeof create>, type: string): number {
  return renderer.root.findAll((n) => n.type === type).length;
}

const base: PrStatus = {
  state: "open",
  merged: false,
  draft: false,
  additions: 0,
  deletions: 0,
};

describe("PrStatusBadge", () => {
  it("renders an open PR badge", () => {
    setStatus({ ...base, state: "open" });
    const r = render({ prUrl: "https://github.com/a/b/pull/1" });
    expect(label(r)).toBe("Open PR");
    expect(iconCount(r, "GitPullRequest")).toBe(1);
  });

  it("renders a merged PR badge with the merge icon", () => {
    setStatus({ ...base, state: "closed", merged: true });
    const r = render({ prUrl: "https://github.com/a/b/pull/1" });
    expect(label(r)).toBe("Open merged PR");
    expect(iconCount(r, "GitMerge")).toBe(1);
    expect(iconCount(r, "GitPullRequest")).toBe(0);
  });

  it("renders a closed PR badge", () => {
    setStatus({ ...base, state: "closed" });
    const r = render({ prUrl: "https://github.com/a/b/pull/1" });
    expect(label(r)).toBe("Open closed PR");
  });

  it("renders a draft PR badge", () => {
    setStatus({ ...base, state: "open", draft: true });
    const r = render({ prUrl: "https://github.com/a/b/pull/1" });
    expect(label(r)).toBe("Open draft PR");
  });

  it.each([
    { data: undefined, label: "loading" },
    { data: null, label: "unresolved (private/404/non-GitHub)" },
  ])(
    "renders nothing when hideWhenUnresolved is set and status is $label",
    ({ data }) => {
      setStatus(data);
      const r = render({
        prUrl: "https://github.com/a/b/pull/1",
        hideWhenUnresolved: true,
      });
      expect(r.toJSON()).toBeNull();
    },
  );

  it("still renders a neutral badge for an unresolved PR by default", () => {
    setStatus(null);
    const r = render({ prUrl: "https://github.com/a/b/pull/1" });
    expect(r.toJSON()).not.toBeNull();
    expect(label(r)).toBe("Open PR");
  });
});
