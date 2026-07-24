import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { TaskSessionView } from "./TaskSessionView";

vi.mock("phosphor-react-native", () => ({
  ArrowDown: (props: Record<string, unknown>) =>
    createElement("ArrowDown", props),
  Brain: (props: Record<string, unknown>) => createElement("Brain", props),
  CaretRight: (props: Record<string, unknown>) =>
    createElement("CaretRight", props),
  CloudArrowDown: (props: Record<string, unknown>) =>
    createElement("CloudArrowDown", props),
  Robot: (props: Record<string, unknown>) => createElement("Robot", props),
}));

vi.mock("@/features/chat", () => ({
  AgentMessage: (props: Record<string, unknown>) =>
    createElement("AgentMessage", props),
  HumanMessage: (props: Record<string, unknown>) =>
    createElement("HumanMessage", props),
  ToolMessage: (props: Record<string, unknown>) =>
    createElement("ToolMessage", props),
  deriveToolKind: () => "other",
}));

vi.mock("@/features/chat/utils/thinkingMessages", () => ({
  getRandomThinkingActivity: () => "Thinking",
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 8: "#888", 9: "#777", 11: "#555" },
    accent: { 9: "#f60" },
    status: { error: "#d00" },
  }),
}));

vi.mock("./PlanStatusBar", () => ({
  PlanStatusBar: (props: Record<string, unknown>) =>
    createElement("PlanStatusBar", props),
}));

vi.mock("./QuestionCard", () => ({
  QuestionCard: (props: Record<string, unknown>) =>
    createElement("QuestionCard", props),
}));

vi.mock("./PlanApprovalCard", () => ({
  PlanApprovalCard: (props: Record<string, unknown>) =>
    createElement("PlanApprovalCard", props),
}));

vi.mock("./CloudMessageAttachment", () => ({
  CloudMessageAttachment: (props: Record<string, unknown>) =>
    createElement("CloudMessageAttachment", props),
}));

function renderTaskSessionView(
  props: Parameters<typeof TaskSessionView>[0],
): ReturnType<typeof create> {
  let renderer!: ReturnType<typeof create>;
  act(() => {
    renderer = create(createElement(TaskSessionView, props));
  });
  return renderer;
}

function findHumanMessages(renderer: ReturnType<typeof create>) {
  // vi.mock'd `HumanMessage` is rendered as the literal string `"HumanMessage"`
  // (an intrinsic), so node.type is a string at runtime even though the type
  // says ElementType.
  return renderer.root.findAll(
    (node) => (node.type as unknown as string) === "HumanMessage",
  );
}

describe("TaskSessionView", () => {
  function userMessageEvent(text: string, ts: number) {
    return {
      type: "session_update" as const,
      ts,
      notification: {
        update: {
          sessionUpdate: "user_message_chunk",
          content: { type: "text", text },
        },
      },
    };
  }

  const SUBMIT_TS = 1000;

  it.each([
    {
      name: "no SSE echo yet → optimistic renders",
      events: [],
      expectedCount: 1,
    },
    {
      name: "matching SSE chunk after submit → optimistic suppressed",
      events: [userMessageEvent("Ship it", SUBMIT_TS + 5)],
      expectedCount: 1,
    },
    {
      name: "text-identical historical turn → optimistic still renders",
      // Same text but ts predates submit — a prior "Ship it" message shouldn't
      // cause the new optimistic echo to be deduped.
      events: [userMessageEvent("Ship it", SUBMIT_TS - 1000)],
      expectedCount: 2,
    },
    {
      name: "non-matching SSE text → optimistic still renders",
      events: [userMessageEvent("Different text", SUBMIT_TS + 5)],
      expectedCount: 2,
    },
  ])("optimistic echo: $name", ({ events, expectedCount }) => {
    const renderer = renderTaskSessionView({
      events,
      optimisticUserMessage: { text: "Ship it", setAt: SUBMIT_TS },
    });

    expect(findHumanMessages(renderer)).toHaveLength(expectedCount);
  });

  it("optimistic echo carries the submitted text into the rendered bubble", () => {
    const renderer = renderTaskSessionView({
      events: [],
      optimisticUserMessage: { text: "Ship it", setAt: SUBMIT_TS },
    });

    const humans = findHumanMessages(renderer);
    expect(humans).toHaveLength(1);
    expect(humans[0].props.content).toBe("Ship it");
  });

  it("keeps question tools pending after the run goes idle", () => {
    const events = [
      {
        type: "session_update" as const,
        ts: 1,
        notification: {
          update: {
            sessionUpdate: "tool_call",
            title: "Which license should I use?",
            toolCallId: "question-1",
            status: "pending" as const,
            rawInput: {
              questions: [
                {
                  question: "Which license should I use?",
                  options: [{ label: "MIT" }],
                },
              ],
            },
            _meta: {
              claudeCode: {
                toolName: "AskUserQuestion",
              },
            },
          },
        },
      },
    ];

    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(TaskSessionView, {
          events,
          isConnecting: false,
          isThinking: true,
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    act(() => {
      renderer.update(
        createElement(TaskSessionView, {
          events,
          isConnecting: false,
          isThinking: false,
        }),
      );
    });

    expect(renderer.root.findByType("QuestionCard").props.toolData.status).toBe(
      "pending",
    );
  });
});
