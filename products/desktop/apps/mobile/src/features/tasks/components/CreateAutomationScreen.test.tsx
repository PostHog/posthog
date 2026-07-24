import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  mockReplace,
  mockBack,
  mockMutateAsync,
  mockUseCreateTaskAutomation,
  mockUseSkillStoreSkill,
  routeParams,
} = vi.hoisted(() => ({
  mockReplace: vi.fn(),
  mockBack: vi.fn(),
  mockMutateAsync: vi.fn(),
  mockUseCreateTaskAutomation: vi.fn(),
  mockUseSkillStoreSkill: vi.fn(),
  routeParams: {} as { skillName?: string | string[] },
}));

vi.mock("expo-router", () => ({
  Stack: {
    Screen: (props: Record<string, unknown>) =>
      createElement("StackScreen", props),
  },
  useLocalSearchParams: () => routeParams,
  useRouter: () => ({
    replace: mockReplace,
    back: mockBack,
  }),
}));

vi.mock("expo-localization", () => ({
  getCalendars: () => [{ timeZone: "UTC" }],
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    background: "#ffffff",
    gray: {
      11: "#666666",
      12: "#111111",
    },
    accent: {
      9: "#ff5500",
    },
  }),
}));

vi.mock("@/features/tasks/hooks/useAutomations", () => ({
  useCreateTaskAutomation: mockUseCreateTaskAutomation,
}));

vi.mock("@/features/tasks/skills/hooks", () => ({
  useSkillStoreSkill: mockUseSkillStoreSkill,
}));

vi.mock("@/features/tasks/components/AutomationForm", () => ({
  AutomationForm: (props: Record<string, unknown>) =>
    createElement("AutomationForm", props),
}));

vi.mock("@/features/tasks/api", () => ({
  TaskAutomationValidationError: class TaskAutomationValidationError extends Error {
    code: string;
    attr: string | null;

    constructor(
      message: string,
      code = "invalid_input",
      attr: string | null = null,
    ) {
      super(message);
      this.code = code;
      this.attr = attr;
    }
  },
}));

import CreateAutomationScreen from "@/app/automation/create";

describe("CreateAutomationScreen", () => {
  beforeEach(() => {
    mockReplace.mockReset();
    mockBack.mockReset();
    mockMutateAsync.mockReset();
    mockUseCreateTaskAutomation.mockReset();
    mockUseSkillStoreSkill.mockReset();
    routeParams.skillName = undefined;

    mockUseCreateTaskAutomation.mockReturnValue({
      isPending: false,
      mutateAsync: mockMutateAsync,
    });
  });

  it("seeds the form from the selected skill and saves a prefixed template id", async () => {
    routeParams.skillName = "shared-daily-brief";
    mockUseSkillStoreSkill.mockReturnValue({
      data: {
        name: "shared-daily-brief",
        description: "Shared briefing starter",
        body: "Summarize the most important work for today.",
      },
      isPending: false,
      error: null,
      refetch: vi.fn(),
    });
    mockMutateAsync.mockResolvedValueOnce({ id: "automation-1" });

    let renderer: ReturnType<typeof create> | null = null;
    act(() => {
      renderer = create(createElement(CreateAutomationScreen));
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const stackScreen = renderer.root.findByType("StackScreen");
    expect(stackScreen.props.options.headerTitle).toBe("Create automation");
    expect(
      renderer.root.findAll(
        (node) => node.props.children === "shared-daily-brief",
      ).length,
    ).toBeGreaterThan(0);
    expect(
      renderer.root.findAll(
        (node) => node.props.children === "Shared briefing starter",
      ).length,
    ).toBe(0);

    const form = renderer.root.findByType("AutomationForm");
    expect(form.props.initialValues).toMatchObject({
      name: "shared-daily-brief",
      prompt: "Summarize the most important work for today.",
      timezone: "UTC",
      enabled: true,
    });
    expect(form.props.initialPromptMode).toBe("preview");

    await act(async () => {
      await form.props.onSubmit({
        name: "shared-daily-brief",
        prompt: "Summarize the most important work for today.",
        repository: "posthog/posthog",
        github_integration: 7,
        cron_expression: "0 9 * * 1-5",
        timezone: "UTC",
        enabled: true,
      });
    });

    expect(mockMutateAsync).toHaveBeenCalledWith({
      name: "shared-daily-brief",
      prompt: "Summarize the most important work for today.",
      repository: "posthog/posthog",
      github_integration: 7,
      cron_expression: "0 9 * * 1-5",
      timezone: "UTC",
      enabled: true,
      template_id: "llm-skill:shared-daily-brief",
    });
    expect(mockReplace).toHaveBeenCalledWith("/automation/automation-1");
  });

  it("keeps scratch creation untemplated when no skill is selected", async () => {
    mockUseSkillStoreSkill.mockReturnValue({
      data: undefined,
      isPending: false,
      error: null,
      refetch: vi.fn(),
    });
    mockMutateAsync.mockResolvedValueOnce({ id: "automation-2" });

    let renderer: ReturnType<typeof create> | null = null;
    act(() => {
      renderer = create(createElement(CreateAutomationScreen));
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const form = renderer.root.findByType("AutomationForm");
    expect(form.props.initialValues).toMatchObject({
      name: undefined,
      prompt: undefined,
      timezone: "UTC",
      enabled: true,
    });
    expect(form.props.initialPromptMode).toBe("edit");

    await act(async () => {
      await form.props.onSubmit({
        name: "Custom automation",
        prompt: "Check the repo every morning.",
        repository: "posthog/posthog",
        github_integration: 7,
        cron_expression: "0 9 * * 1-5",
        timezone: "UTC",
        enabled: true,
      });
    });

    expect(mockMutateAsync).toHaveBeenCalledWith({
      name: "Custom automation",
      prompt: "Check the repo every morning.",
      repository: "posthog/posthog",
      github_integration: 7,
      cron_expression: "0 9 * * 1-5",
      timezone: "UTC",
      enabled: true,
      template_id: null,
    });
  });
});
