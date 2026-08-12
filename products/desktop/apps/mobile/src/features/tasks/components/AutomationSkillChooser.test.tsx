import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

const { mockUseSkillStoreSkills } = vi.hoisted(() => ({
  mockUseSkillStoreSkills: vi.fn(),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: {
      9: "#666666",
    },
    accent: {
      9: "#ff5500",
    },
  }),
}));

vi.mock("../skills/hooks", () => ({
  useSkillStoreSkills: mockUseSkillStoreSkills,
}));

vi.mock("./AutomationSkillCard", () => ({
  AutomationSkillCard: ({
    skill,
    onPress,
  }: {
    skill: { name: string };
    onPress: (skillName: string) => void;
  }) =>
    createElement(
      "AutomationSkillCard",
      {
        onPress: () => onPress(skill.name),
        title: skill.name,
      },
      skill.name,
    ),
}));

import { AutomationSkillChooser } from "./AutomationSkillChooser";

describe("AutomationSkillChooser", () => {
  it("renders start from scratch before skill-store entries", () => {
    mockUseSkillStoreSkills.mockReturnValue({
      data: [
        { name: "shared-daily-brief", description: "Briefing starter" },
        { name: "shared-pr-triage", description: "PR triage starter" },
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    let renderer: ReturnType<typeof create> | null = null;
    act(() => {
      renderer = create(
        createElement(AutomationSkillChooser, {
          onCreateCustom: vi.fn(),
          onSelectSkill: vi.fn(),
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const labels = renderer.root
      .findAll((node) => typeof node.props.children === "string")
      .map((node) => node.props.children);

    expect(labels).toContain("Start from scratch");
    expect(labels).toContain("shared-daily-brief");
    expect(labels).toContain("shared-pr-triage");
    expect(labels.indexOf("Start from scratch")).toBeLessThan(
      labels.indexOf("shared-daily-brief"),
    );
  });

  it("routes scratch and skill selections through the expected callbacks", () => {
    mockUseSkillStoreSkills.mockReturnValue({
      data: [{ name: "shared-daily-brief", description: "Briefing starter" }],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    const onCreateCustom = vi.fn();
    const onSelectSkill = vi.fn();
    let renderer: ReturnType<typeof create> | null = null;
    act(() => {
      renderer = create(
        createElement(AutomationSkillChooser, {
          onCreateCustom,
          onSelectSkill,
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const buttons = renderer.root.findAll(
      (node) => typeof node.props.onPress === "function",
    );
    const skillCard = renderer.root.findByType("AutomationSkillCard");

    buttons[0]?.props.onPress();
    skillCard.props.onPress();

    expect(onCreateCustom).toHaveBeenCalledOnce();
    expect(onSelectSkill).toHaveBeenCalledWith("shared-daily-brief");
  });

  it("filters the skill list by search text and shows a no-match state", () => {
    mockUseSkillStoreSkills.mockReturnValue({
      data: [
        { name: "shared-daily-brief", description: "Morning update" },
        { name: "shared-pr-triage", description: "Pull request queue" },
      ],
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });

    let renderer: ReturnType<typeof create> | null = null;
    act(() => {
      renderer = create(
        createElement(AutomationSkillChooser, {
          onCreateCustom: vi.fn(),
          onSelectSkill: vi.fn(),
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const searchInput = renderer.root.findByProps({
      placeholder: "Search skills",
    });

    act(() => {
      searchInput.props.onChangeText("triage");
    });

    expect(renderer.root.findAllByType("AutomationSkillCard")).toHaveLength(1);
    expect(renderer.root.findByType("AutomationSkillCard").props.title).toBe(
      "shared-pr-triage",
    );

    act(() => {
      searchInput.props.onChangeText("missing");
    });

    expect(renderer.root.findAllByType("AutomationSkillCard")).toHaveLength(0);
    expect(
      renderer.root.findAll(
        (node) => node.props.children === "No matching skills",
      ).length,
    ).toBeGreaterThan(0);
  });
});
