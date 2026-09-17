import type { LoopSchemas } from "@posthog/api-client/loops";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LoopsListViewPresentation } from "./LoopsListView";

vi.mock("./LoopBuilderComposer", () => ({
  LoopBuilderComposer: () => null,
}));
vi.mock("./LoopTemplatesSection", () => ({
  LoopTemplatesSection: () => null,
}));
vi.mock("./LoopRow", () => ({
  LoopRow: ({ loop }: { loop: LoopSchemas.Loop }) => <div>{loop.name}</div>,
}));

const LOOP = {
  id: "loop-1",
  name: "team loop",
  visibility: "team",
  created_by_id: 1,
} as LoopSchemas.Loop;

describe("LoopsListViewPresentation", () => {
  // The three resolution states share one ternary; a reorder would show rows
  // over a skeleton or hide the failure behind an empty list.
  it.each([
    { state: "loading", props: { isLoading: true }, showsRows: false },
    {
      state: "error",
      props: { error: new Error("workflows are down") },
      showsRows: false,
    },
    { state: "loaded", props: {}, showsRows: true },
  ])("renders the $state state", ({ props, showsRows }) => {
    render(
      <LoopsListViewPresentation
        loops={[LOOP]}
        onStartBlank={vi.fn()}
        onStartFromTemplate={vi.fn()}
        {...props}
      />,
    );

    expect(screen.queryByText("team loop") !== null).toBe(showsRows);
    if ("error" in props) {
      expect(screen.getByText("workflows are down")).toBeVisible();
    }
  });
});
