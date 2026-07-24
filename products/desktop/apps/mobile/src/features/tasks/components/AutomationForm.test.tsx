import { createElement } from "react";
import { TextInput } from "react-native";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

const { mockUseIntegrations } = vi.hoisted(() => ({
  mockUseIntegrations: vi.fn(),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: {
      9: "#666666",
      12: "#111111",
    },
    accent: {
      9: "#ff5500",
      contrast: "#ffffff",
    },
  }),
}));

vi.mock("../hooks/useIntegrations", () => ({
  useIntegrations: mockUseIntegrations,
}));

vi.mock("./GitHubConnectionPrompt", () => ({
  GitHubConnectionPrompt: (props: Record<string, unknown>) =>
    createElement("GitHubConnectionPrompt", props),
}));

vi.mock("./GitHubLoadNotice", () => ({
  GitHubLoadNotice: (props: Record<string, unknown>) =>
    createElement("GitHubLoadNotice", props, props.message as string),
}));

vi.mock("../composer/RepositoryPickerInline", () => ({
  RepositoryPickerInline: (props: Record<string, unknown>) =>
    createElement("RepositoryPickerInline", props),
}));

vi.mock("./ScheduleEditor", () => ({
  ScheduleEditor: (props: Record<string, unknown>) =>
    createElement("ScheduleEditor", props),
}));

vi.mock("@/features/chat/components/MarkdownText", () => ({
  MarkdownText: (props: Record<string, unknown>) =>
    createElement("MarkdownText", props),
}));

import { AutomationForm } from "./AutomationForm";

describe("AutomationForm", () => {
  it("submits successfully when repository selection is optional", async () => {
    mockUseIntegrations.mockReturnValue({
      error: null,
      hasGithubIntegration: null,
      repositoryOptions: [],
      repositoryWarning: null,
      isLoading: false,
      refetch: vi.fn(),
    });
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(AutomationForm, {
          initialValues: {
            name: "PM product pulse",
            prompt: "Summarize my product signals",
            timezone: "UTC",
            enabled: true,
          },
          isSubmitting: false,
          submitLabel: "Create automation",
          repositoryRequired: false,
          onSubmit,
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    // Repository picker is only mounted when `repositoryRequired` is true.
    expect(renderer.root.findAllByType("RepositoryPickerInline")).toHaveLength(
      0,
    );

    const submitButton = renderer.root
      .findAll(
        (node) =>
          typeof node.props.onPress === "function" &&
          node.props.disabled === false,
      )
      .at(-1);

    await act(async () => {
      await submitButton?.props.onPress();
    });

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "PM product pulse",
        prompt: "Summarize my product signals",
        repository: "",
        github_integration: null,
        timezone: "UTC",
      }),
    );
  });

  it("shows the GitHub connection prompt when repository access is required", () => {
    mockUseIntegrations.mockReturnValue({
      error: null,
      hasGithubIntegration: false,
      repositoryOptions: [],
      repositoryWarning: null,
      isLoading: false,
      refetch: vi.fn(),
    });
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(AutomationForm, {
          initialValues: {
            name: "Developer morning briefing",
            prompt: "Summarize my PRs",
            timezone: "UTC",
            enabled: true,
          },
          isSubmitting: false,
          submitLabel: "Create automation",
          repositoryRequired: true,
          onSubmit: vi.fn(),
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    expect(renderer.root.findAllByType("GitHubConnectionPrompt")).toHaveLength(
      1,
    );
  });

  it("renders markdown preview when the prompt starts in preview mode", () => {
    mockUseIntegrations.mockReturnValue({
      error: null,
      hasGithubIntegration: null,
      repositoryOptions: [],
      repositoryWarning: null,
      isLoading: false,
      refetch: vi.fn(),
    });
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(AutomationForm, {
          initialValues: {
            name: "Daily brief",
            prompt: "## Summary\n- Check PRs",
            timezone: "UTC",
            enabled: true,
          },
          initialPromptMode: "preview",
          isSubmitting: false,
          submitLabel: "Create automation",
          repositoryRequired: false,
          onSubmit: vi.fn(),
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    expect(renderer.root.findAllByType(TextInput)).toHaveLength(1);
    expect(renderer.root.findByType("MarkdownText").props.content).toBe(
      "## Summary\n- Check PRs",
    );
  });

  it("requires repository selection for repo-backed submissions", async () => {
    mockUseIntegrations.mockReturnValue({
      error: null,
      hasGithubIntegration: true,
      repositoryOptions: [
        {
          integrationId: 7,
          integrationLabel: "PostHog",
          repository: "posthog/posthog",
        },
      ],
      repositoryWarning: null,
      isLoading: false,
      refetch: vi.fn(),
    });
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(AutomationForm, {
          initialValues: {
            name: "Developer morning briefing",
            prompt: "Summarize my PRs",
            timezone: "UTC",
            enabled: true,
          },
          isSubmitting: false,
          submitLabel: "Create automation",
          repositoryRequired: true,
          onSubmit,
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const repositoryPicker = renderer.root.findByType("RepositoryPickerInline");

    // The new picker emits `RepositoryOption` objects (with the integration
    // label too) rather than the raw `RepositorySelection` shape used by
    // the old inline list.
    act(() => {
      repositoryPicker.props.onChange({
        integrationId: 7,
        integrationLabel: "PostHog",
        repository: "posthog/posthog",
      });
    });

    const submitButton = renderer.root
      .findAll(
        (node) =>
          typeof node.props.onPress === "function" &&
          node.props.disabled === false,
      )
      .at(-1);

    await act(async () => {
      await submitButton?.props.onPress();
    });

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        repository: "posthog/posthog",
        github_integration: 7,
      }),
    );
  });
});
