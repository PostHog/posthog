import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockPosthog = {
  register: vi.fn(),
  unregister: vi.fn(),
  capture: vi.fn(),
};
vi.mock("posthog-react-native", () => ({ usePostHog: () => mockPosthog }));
vi.mock("expo-haptics", () => ({
  impactAsync: vi.fn(),
  ImpactFeedbackStyle: { Light: "light" },
}));
vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: { 9: "#000000" } }),
}));

import { useTurnFeedbackStore } from "@/features/tasks/stores/turnFeedbackStore";
import { TurnFeedback } from "./TurnFeedback";

function render(props: { turnId: string; taskId?: string | null }) {
  let renderer: ReactTestRenderer | null = null;
  act(() => {
    renderer = create(createElement(TurnFeedback, props));
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReactTestRenderer;
}

function press(renderer: ReactTestRenderer, label: string) {
  const node = renderer.root.findAll(
    (n) => n.props?.accessibilityLabel === label,
  )[0];
  act(() => node.props.onPress());
}

function storedSentiment(turnId: string) {
  return useTurnFeedbackStore.getState().sentimentByTurnId[turnId] ?? null;
}

describe("TurnFeedback", () => {
  beforeEach(() => {
    mockPosthog.capture.mockReset();
    useTurnFeedbackStore.setState({ sentimentByTurnId: {} });
  });

  it("records feedback on the first tap", () => {
    const renderer = render({ turnId: "agent-0", taskId: "task-1" });
    press(renderer, "Good response");
    expect(mockPosthog.capture).toHaveBeenCalledTimes(1);
    expect(mockPosthog.capture).toHaveBeenCalledWith("Agent turn feedback", {
      task_id: "task-1",
      turn_id: "agent-0",
      sentiment: "positive",
    });
    expect(storedSentiment("agent-0")).toBe("positive");
  });

  it("ignores a re-tap of the already-lit thumb", () => {
    const renderer = render({ turnId: "agent-0", taskId: "task-1" });
    press(renderer, "Good response");
    press(renderer, "Good response");
    expect(mockPosthog.capture).toHaveBeenCalledTimes(1);
  });

  it("records the new sentiment when switching thumbs", () => {
    const renderer = render({ turnId: "agent-0", taskId: "task-1" });
    press(renderer, "Good response");
    press(renderer, "Bad response");
    expect(mockPosthog.capture).toHaveBeenCalledTimes(2);
    expect(mockPosthog.capture).toHaveBeenLastCalledWith(
      "Agent turn feedback",
      {
        task_id: "task-1",
        turn_id: "agent-0",
        sentiment: "negative",
      },
    );
    expect(storedSentiment("agent-0")).toBe("negative");
  });

  it("sends a null task_id when no task is provided", () => {
    const renderer = render({ turnId: "agent-0" });
    press(renderer, "Bad response");
    expect(mockPosthog.capture).toHaveBeenCalledWith("Agent turn feedback", {
      task_id: null,
      turn_id: "agent-0",
      sentiment: "negative",
    });
  });
});
