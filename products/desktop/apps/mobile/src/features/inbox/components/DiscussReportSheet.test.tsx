import { createElement } from "react";
import { act, create, type ReactTestInstance } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

type Renderer = ReturnType<typeof create>;

const mocks = vi.hoisted(() => ({ onSubmit: vi.fn() }));

vi.mock("expo-haptics", () => ({
  impactAsync: vi.fn(),
  ImpactFeedbackStyle: { Light: "light" },
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: { 9: "#888" } }),
}));

// The real sheet wraps its body in a Modal, which the test renderer draws as
// null. Render the children directly so the composer and rows are inspectable.
vi.mock("@/components/SheetContainer", () => ({
  SheetContainer: (props: { children?: unknown }) =>
    createElement("SheetContainer", null, props.children as never),
}));

import { DiscussReportSheet } from "./DiscussReportSheet";

function mount(suggestedPrompts?: string[]) {
  let renderer: Renderer | null = null;
  act(() => {
    renderer = create(
      createElement(DiscussReportSheet, {
        visible: true,
        reportId: "report-1",
        reportTitle: "Checkout failures",
        suggestedPrompts,
        onClose: vi.fn(),
        onSubmit: mocks.onSubmit,
      }),
    );
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as Renderer;
}

function questionInput(renderer: Renderer) {
  return renderer.root.find(
    (node: ReactTestInstance) =>
      node.props.placeholder === "What do you want to know?",
  );
}

function suggestionRow(renderer: Renderer, text: string) {
  const rows = renderer.root.findAll(
    (n: ReactTestInstance) =>
      n.props.accessibilityRole === "button" && n.props.onPress,
  );
  const row = rows.find(
    (n) =>
      n.findAll((c: ReactTestInstance) => c.props.children === text).length,
  );
  if (!row) throw new Error(`No suggestion row for "${text}"`);
  return row;
}

describe("DiscussReportSheet", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows no suggested questions when the report has none", () => {
    const renderer = mount();
    expect(
      renderer.root.findAll(
        (node) => node.props.children === "Suggested questions",
      ),
    ).toHaveLength(0);
  });

  it("fills the composer from a suggestion without submitting", () => {
    const renderer = mount(["Why did checkout fail?", "Which teams hit it?"]);

    act(() => {
      suggestionRow(renderer, "Why did checkout fail?").props.onPress();
    });

    expect(questionInput(renderer).props.value).toBe("Why did checkout fail?");
    expect(mocks.onSubmit).not.toHaveBeenCalled();
  });

  it("submits the filled suggestion only when the reader presses Discuss", () => {
    const renderer = mount(["Why did checkout fail?"]);

    act(() => {
      suggestionRow(renderer, "Why did checkout fail?").props.onPress();
    });
    act(() => {
      renderer.root
        .find((node) => node.props.accessibilityLabel === "Start discussion")
        .props.onPress();
    });

    expect(mocks.onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ question: "Why did checkout fail?" }),
    );
  });
});
