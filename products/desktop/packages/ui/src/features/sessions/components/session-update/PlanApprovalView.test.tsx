import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PlanApprovalView } from "./PlanApprovalView";

const PLAN_MARKER = "Sentinel plan body for testing";

function makeToolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    toolCallId: "tc-1",
    title: "Ready to code?",
    kind: "switch_mode",
    status: "pending",
    rawInput: { plan: PLAN_MARKER },
    ...overrides,
  };
}

function renderView(props: {
  toolCall: ToolCall;
  turnCancelled?: boolean;
  turnComplete?: boolean;
}) {
  return render(
    <Theme>
      <PlanApprovalView {...props} />
    </Theme>,
  );
}

describe("PlanApprovalView", () => {
  it("renders the full plan and no toggle while pending", () => {
    renderView({ toolCall: makeToolCall({ status: "pending" }) });

    expect(screen.getByText(PLAN_MARKER)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /show plan/i }),
    ).not.toBeInTheDocument();
  });

  it("hides the plan once approved and exposes a show plan toggle", () => {
    renderView({ toolCall: makeToolCall({ status: "completed" }) });

    expect(
      screen.getByText(/plan approved — proceeding with implementation/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(PLAN_MARKER)).not.toBeInTheDocument();

    const toggle = screen.getByRole("button", { name: /show plan/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("expands and collapses the plan when the toggle is clicked", async () => {
    const user = userEvent.setup();
    renderView({ toolCall: makeToolCall({ status: "completed" }) });

    const toggle = screen.getByRole("button", { name: /show plan/i });
    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByRole("button", { name: /hide plan/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(PLAN_MARKER)).toBeInTheDocument();

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(PLAN_MARKER)).not.toBeInTheDocument();
  });

  it("shows the not-approved status with a working toggle when cancelled", async () => {
    const user = userEvent.setup();
    renderView({
      toolCall: makeToolCall({ status: "pending" }),
      turnCancelled: true,
    });

    expect(screen.getByText(/\(plan not approved\)/i)).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: /show plan/i });

    await user.click(toggle);
    expect(screen.getByText(PLAN_MARKER)).toBeInTheDocument();
  });

  it("shows the not-approved status when the plan tool call fails", () => {
    renderView({ toolCall: makeToolCall({ status: "failed" }) });

    expect(screen.getByText(/\(plan not approved\)/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /show plan/i }),
    ).toBeInTheDocument();
  });

  it("renders historical plans without claiming they were approved", () => {
    renderView({
      toolCall: makeToolCall({
        status: "completed",
        rawInput: { plan: PLAN_MARKER, historical: true },
      }),
    });

    expect(screen.getByText(/^plan$/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/plan approved — proceeding with implementation/i),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /show plan/i }),
    ).toBeInTheDocument();
  });

  it("uses updated content instead of stale raw input while streaming", () => {
    renderView({
      toolCall: makeToolCall({
        status: "in_progress",
        rawInput: { plan: "Initial plan" },
        content: [
          {
            type: "content",
            content: { type: "text", text: "Updated plan" },
          },
        ],
      }),
    });

    expect(screen.getByText("Updated plan")).toBeInTheDocument();
    expect(screen.queryByText("Initial plan")).not.toBeInTheDocument();
  });

  it("omits the toggle when there is no plan text available", () => {
    renderView({
      toolCall: makeToolCall({
        status: "completed",
        rawInput: undefined,
        content: [],
      }),
    });

    expect(
      screen.getByText(/plan approved — proceeding with implementation/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /show plan/i }),
    ).not.toBeInTheDocument();
  });
});
