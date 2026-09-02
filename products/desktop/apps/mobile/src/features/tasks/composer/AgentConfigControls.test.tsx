import type {
  CloudTaskConfigOption,
  CloudTaskConfigSelectGroup,
} from "@posthog/shared";
import { createElement, type ReactNode } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { AgentConfigControls } from "./AgentConfigControls";

const flagState = { fastMode: false as boolean };

vi.mock("posthog-react-native", () => ({
  useFeatureFlag: () => flagState.fastMode,
}));

vi.mock("phosphor-react-native", () => {
  const icon = (name: string) => (props: Record<string, unknown>) =>
    createElement(name, props);
  return {
    ArrowCounterClockwise: icon("ArrowCounterClockwise"),
    CaretDown: icon("CaretDown"),
    Check: icon("Check"),
    Cpu: icon("Cpu"),
    Lightning: icon("Lightning"),
    PauseIcon: icon("PauseIcon"),
    PencilIcon: icon("PencilIcon"),
    Robot: icon("Robot"),
    ShieldCheck: icon("ShieldCheck"),
    Sparkle: icon("Sparkle"),
  };
});

vi.mock("@/components/SheetContainer", () => ({
  SheetContainer: ({
    open,
    children,
  }: {
    open: boolean;
    children: ReactNode;
  }) => (open ? createElement("SheetContainer", null, children) : null),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 10: "#777", 11: "#555", 12: "#111" },
    accent: { 9: "#f60", 11: "#f60" },
    status: { warning: "#d97706" },
    background: "#fff",
  }),
}));

const HARNESS_META = "posthog.code/modelHarness";

const ladderModelOption: CloudTaskConfigOption = {
  id: "model",
  name: "Model",
  type: "select",
  currentValue: "claude-sonnet-5",
  options: [
    { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
    { value: "claude-opus-5", name: "Claude Opus 5" },
    { value: "claude-fable-5", name: "Claude Fable 5" },
  ],
  category: "model",
  description: "Choose a model",
};

const configOptions: CloudTaskConfigOption[] = [ladderModelOption];

const modelGroups: CloudTaskConfigSelectGroup[] = [
  {
    group: "anthropic",
    name: "Anthropic",
    options: [
      {
        value: "claude-sonnet-5",
        name: "Claude Sonnet 5",
        _meta: { [HARNESS_META]: "claude" },
      },
      {
        value: "claude-opus-5",
        name: "Claude Opus 5",
        _meta: { [HARNESS_META]: "claude" },
      },
      {
        value: "claude-fable-5",
        name: "Claude Fable 5",
        _meta: { [HARNESS_META]: "claude" },
      },
    ],
  },
  {
    group: "openai",
    name: "OpenAI",
    options: [
      {
        value: "gpt-5.6-sol",
        name: "GPT-5.6 Sol",
        _meta: { [HARNESS_META]: "codex" },
      },
    ],
  },
];

function baseProps() {
  return {
    adapter: "claude" as const,
    mode: "plan" as const,
    model: "claude-sonnet-5",
    reasoning: "medium" as const,
    contextWindow: "1m" as const,
    fastMode: false,
    configOptions,
    modelGroups,
    onAdapterChange: vi.fn(),
    onModeChange: vi.fn(),
    onModelChange: vi.fn(),
    onReasoningChange: vi.fn(),
    onContextWindowChange: vi.fn(),
    onFastModeChange: vi.fn(),
  };
}

function findPressableWithText(
  renderer: ReturnType<typeof create>,
  label: string,
) {
  return renderer.root.find(
    (node) =>
      typeof node.props.onPress === "function" &&
      node.findAll((child) => child.props.children === label).length > 0,
  );
}

function render(props: ReturnType<typeof baseProps>) {
  let renderer!: ReturnType<typeof create>;
  act(() => {
    renderer = create(createElement(AgentConfigControls, props));
  });
  return renderer;
}

describe("AgentConfigControls", () => {
  it("summarizes model and reasoning in a single pill", () => {
    const renderer = render(baseProps());
    expect(() =>
      findPressableWithText(renderer, "Claude Sonnet 5 · Medium"),
    ).not.toThrow();
  });

  it("applies model and effort together when a preset is picked", () => {
    const props = baseProps();
    const renderer = render(props);

    act(() =>
      findPressableWithText(
        renderer,
        "Claude Sonnet 5 · Medium",
      ).props.onPress(),
    );
    act(() =>
      findPressableWithText(
        renderer,
        "Claude Opus 5 · Extra High",
      ).props.onPress(),
    );

    expect(props.onModelChange).toHaveBeenCalledWith("claude-opus-5");
    expect(props.onReasoningChange).toHaveBeenCalledWith("xhigh");
  });

  it("switches harness when picking a model from the other harness", () => {
    const props = baseProps();
    const renderer = render(props);

    act(() =>
      findPressableWithText(
        renderer,
        "Claude Sonnet 5 · Medium",
      ).props.onPress(),
    );
    act(() => findPressableWithText(renderer, "Advanced").props.onPress());
    act(() => findPressableWithText(renderer, "GPT-5.6 Sol").props.onPress());

    expect(props.onAdapterChange).toHaveBeenCalledWith({
      adapter: "codex",
      mode: "auto",
      model: "gpt-5.6-sol",
      reasoning: "high",
    });
    expect(props.onModelChange).not.toHaveBeenCalled();
  });

  it("keeps a same-harness pick on the current adapter", () => {
    const props = baseProps();
    const renderer = render(props);

    act(() =>
      findPressableWithText(
        renderer,
        "Claude Sonnet 5 · Medium",
      ).props.onPress(),
    );
    act(() => findPressableWithText(renderer, "Advanced").props.onPress());
    act(() => findPressableWithText(renderer, "Claude Opus 5").props.onPress());

    expect(props.onModelChange).toHaveBeenCalledWith("claude-opus-5");
    expect(props.onAdapterChange).not.toHaveBeenCalled();
  });

  it("hides the other harness's models when the run locks the adapter", () => {
    const props = { ...baseProps(), canChangeAdapter: false };
    const renderer = render(props);

    act(() =>
      findPressableWithText(
        renderer,
        "Claude Sonnet 5 · Medium",
      ).props.onPress(),
    );
    act(() => findPressableWithText(renderer, "Advanced").props.onPress());

    expect(() => findPressableWithText(renderer, "GPT-5.6 Sol")).toThrow();
    expect(() =>
      findPressableWithText(renderer, "Claude Opus 5"),
    ).not.toThrow();
  });

  it("only surfaces the fast mode toggle when the flag is on and the model supports it", () => {
    flagState.fastMode = true;
    const props = { ...baseProps(), model: "claude-opus-5" };
    const renderer = render(props);

    act(() =>
      findPressableWithText(renderer, "Claude Opus 5 · Medium").props.onPress(),
    );
    expect(() => renderer.root.findByType("Lightning" as never)).not.toThrow();

    flagState.fastMode = false;
  });
});
