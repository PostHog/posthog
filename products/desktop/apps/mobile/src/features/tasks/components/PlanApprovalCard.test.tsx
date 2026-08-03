import { createElement } from "react";
import { TextInput } from "react-native";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { PlanApprovalCard } from "./PlanApprovalCard";

vi.mock("phosphor-react-native", () => ({
  ArrowsClockwise: (props: Record<string, unknown>) =>
    createElement("ArrowsClockwise", props),
  ChatCircle: (props: Record<string, unknown>) =>
    createElement("ChatCircle", props),
  CheckCircle: (props: Record<string, unknown>) =>
    createElement("CheckCircle", props),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: {
      9: "#666666",
      11: "#444444",
    },
    accent: {
      9: "#ff5500",
    },
    status: {
      success: "#00aa55",
    },
  }),
}));

vi.mock("@/features/chat", () => ({
  MarkdownText: (props: Record<string, unknown>) =>
    createElement("MarkdownText", props),
}));

function findPressableWithText(
  renderer: NonNullable<ReturnType<typeof create>>,
  label: string,
) {
  return renderer.root.find(
    (node) =>
      typeof node.props.onPress === "function" &&
      node.findAll((child) => child.props.children === label).length > 0,
  );
}

describe("PlanApprovalCard", () => {
  it("renders the plan with the markdown renderer", () => {
    const plan = "# Plan\n\n1. Inspect renderer\n2. Fix markdown output";
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(PlanApprovalCard, {
          toolData: {
            toolCallId: "tool-plan",
            status: "pending",
          },
          permission: {
            requestId: "request-plan",
            toolCall: {
              toolCallId: "tool-plan",
              title: "Ready to code?",
              kind: "switch_mode",
              rawInput: { plan },
            },
            options: [
              {
                kind: "allow_once",
                optionId: "default",
                name: "Yes, and manually approve edits",
              },
            ],
          },
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    expect(renderer.root.findByType("MarkdownText").props.content).toBe(plan);
  });

  it("sends the selected approval option immediately", () => {
    const onSendPermissionResponse = vi.fn();
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(PlanApprovalCard, {
          toolData: {
            toolCallId: "tool-1",
            status: "pending",
          },
          permission: {
            requestId: "request-1",
            toolCall: {
              toolCallId: "tool-1",
              title: "Ready to code?",
              kind: "switch_mode",
            },
            options: [
              {
                kind: "allow_once",
                optionId: "default",
                name: "Yes, and manually approve edits",
              },
            ],
          },
          onSendPermissionResponse,
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const approveButton = findPressableWithText(
      renderer,
      "Yes, and manually approve edits",
    );

    act(() => {
      approveButton.props.onPress();
    });

    expect(onSendPermissionResponse).toHaveBeenCalledWith({
      toolCallId: "tool-1",
      optionId: "default",
      displayText: "Yes, and manually approve edits",
    });
  });

  it("collects feedback before sending the reject option", () => {
    const onSendPermissionResponse = vi.fn();
    let renderer: ReturnType<typeof create> | null = null;

    act(() => {
      renderer = create(
        createElement(PlanApprovalCard, {
          toolData: {
            toolCallId: "tool-2",
            status: "pending",
          },
          permission: {
            requestId: "request-2",
            toolCall: {
              toolCallId: "tool-2",
              title: "Ready to code?",
              kind: "switch_mode",
            },
            options: [
              {
                kind: "reject_once",
                optionId: "reject_with_feedback",
                name: "No, and tell the agent what to do differently",
                _meta: { customInput: true },
              },
            ],
          },
          onSendPermissionResponse,
        }),
      );
    });

    if (!renderer) {
      throw new Error("Renderer not created");
    }

    const feedbackOption = findPressableWithText(
      renderer,
      "No, and tell the agent what to do differently",
    );

    act(() => {
      feedbackOption.props.onPress();
    });

    const input = renderer.root.findByType(TextInput);
    act(() => {
      input.props.onChangeText("Keep the rollback plan tighter.");
    });

    const sendButton = findPressableWithText(renderer, "Send feedback");
    act(() => {
      sendButton.props.onPress();
    });

    expect(onSendPermissionResponse).toHaveBeenCalledWith({
      toolCallId: "tool-2",
      optionId: "reject_with_feedback",
      customInput: "Keep the rollback plan tighter.",
      displayText: "Keep the rollback plan tighter.",
    });
  });
});
