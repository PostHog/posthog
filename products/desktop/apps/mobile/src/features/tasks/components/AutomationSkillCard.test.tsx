import type { LlmSkillListItem } from "@posthog/api-client/posthog-client";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    accent: {
      11: "#ff5500",
    },
  }),
}));

vi.mock("phosphor-react-native", () => ({
  CaretDown: (props: Record<string, unknown>) =>
    createElement("CaretDown", props),
  CaretUp: (props: Record<string, unknown>) => createElement("CaretUp", props),
}));

import { AutomationSkillCard } from "./AutomationSkillCard";

/** The card only reads `name` and `description`; the rest is list-shape ballast. */
function skillFixture(description: string): LlmSkillListItem {
  return {
    id: "skill-1",
    name: "shared-daily-brief",
    description,
    allowed_tools: [],
    metadata: {},
    version: 1,
    is_latest: true,
    created_by: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("AutomationSkillCard", () => {
  it("collapses long descriptions by default and expands on demand", () => {
    const onPress = vi.fn();
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(AutomationSkillCard, {
          skill: skillFixture(
            "A longer description that should overflow two lines in the card preview when measured by the native text layout callback.",
          ),
          onPress,
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const descriptionText =
      "A longer description that should overflow two lines in the card preview when measured by the native text layout callback.";
    const visibleDescriptionNode = renderer.root.findAll(
      (node) =>
        node.props.numberOfLines === 2 &&
        node.props.children === descriptionText,
    )[0];
    const measurementNode = renderer.root.findAll(
      (node) =>
        typeof node.props.onTextLayout === "function" &&
        node.props.children === descriptionText,
    )[0];

    if (!visibleDescriptionNode || !measurementNode) {
      throw new Error("Description node not found");
    }

    expect(visibleDescriptionNode.props.numberOfLines).toBe(2);

    act(() => {
      measurementNode.props.onTextLayout({
        nativeEvent: {
          lines: [{}, {}, {}],
        },
      });
    });

    const toggle = renderer.root.findAll(
      (node) =>
        typeof node.props.onPress === "function" &&
        node.props.children?.[1]?.props?.children === "Show more",
    )[0];

    act(() => {
      toggle.props.onPress({ stopPropagation: vi.fn() });
    });

    const updatedDescriptionNode = renderer.root.findAll(
      (node) =>
        node.props.children === descriptionText &&
        "numberOfLines" in node.props &&
        node.props.children === descriptionText,
    )[0];

    expect(updatedDescriptionNode?.props.numberOfLines).toBeUndefined();
    expect(
      renderer.root.findAll((node) => node.props.children === "Show less")
        .length,
    ).toBeGreaterThan(0);
  });
});
