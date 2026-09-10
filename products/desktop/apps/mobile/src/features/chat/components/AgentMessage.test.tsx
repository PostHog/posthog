import { type ComponentProps, createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/core/sessions/thinkingActivities", () => ({
  pickThinkingActivity: () => "thinking",
}));
vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: {}, status: {} }),
}));
vi.mock("@/lib/format", () => ({ formatRelativeTime: () => "now" }));
vi.mock("../hooks/usePeriodicRerender", () => ({
  usePeriodicRerender: () => {},
}));
vi.mock("./MarkdownText", () => ({ MarkdownText: () => null }));
vi.mock("./ToolMessage", () => ({ ToolMessage: () => null }));
vi.mock("./CopyButton", () => ({
  CopyButton: (props: Record<string, unknown>) =>
    createElement("CopyButton", props),
}));
vi.mock("./TurnFeedback", () => ({
  TurnFeedback: (props: Record<string, unknown>) =>
    createElement("TurnFeedback", props),
}));

import { AgentMessage } from "./AgentMessage";

function render(props: ComponentProps<typeof AgentMessage>) {
  let renderer: ReactTestRenderer | null = null;
  act(() => {
    renderer = create(createElement(AgentMessage, props));
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReactTestRenderer;
}

function hasTurnFeedback(renderer: ReactTestRenderer) {
  return (
    renderer.root.findAll((n) => String(n.type) === "TurnFeedback").length > 0
  );
}

describe("AgentMessage", () => {
  it("shows the thumbs on a completed agent turn", () => {
    const renderer = render({
      content: "A reply",
      timestamp: 1,
      turnId: "agent-0",
      taskId: "task-1",
    });
    expect(hasTurnFeedback(renderer)).toBe(true);
  });

  it("hides the thumbs while the turn is still streaming", () => {
    const renderer = render({
      content: "partial",
      isLoading: true,
      turnId: "agent-0",
      taskId: "task-1",
    });
    expect(hasTurnFeedback(renderer)).toBe(false);
  });

  it("hides the thumbs when there is no turn id", () => {
    const renderer = render({ content: "A reply", timestamp: 1 });
    expect(hasTurnFeedback(renderer)).toBe(false);
  });
});
