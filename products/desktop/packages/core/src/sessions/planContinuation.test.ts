import type { PermissionRequest } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildApprovedPlanContinuationPrompt,
  CLEAR_AND_CONTINUE_OPTION_ID,
  extractPlanMarkdownFromPermission,
  isClearAndContinueOption,
  isPlanApprovalAcceptOption,
  isPlanApprovalPermission,
  resolveClearAndContinueExecutionMode,
  shouldContinueFromApprovedPlan,
  toApprovedExecutionMode,
} from "./planContinuation";

function makePermission(
  overrides: Partial<PermissionRequest> & {
    toolCall?: PermissionRequest["toolCall"];
  } = {},
): PermissionRequest {
  return {
    taskRunId: "run-1",
    receivedAt: 0,
    options: [],
    ...overrides,
  } as PermissionRequest;
}

describe("planContinuation", () => {
  it("detects plan approval permissions", () => {
    expect(
      isPlanApprovalPermission(
        makePermission({ toolCall: { kind: "switch_mode" } as never }),
      ),
    ).toBe(true);
    expect(
      isPlanApprovalPermission(
        makePermission({ toolCall: { kind: "execute" } as never }),
      ),
    ).toBe(false);
  });

  it("recognizes approve option ids", () => {
    expect(isPlanApprovalAcceptOption("auto")).toBe(true);
    expect(isPlanApprovalAcceptOption("reject_with_feedback")).toBe(false);
    expect(isClearAndContinueOption(CLEAR_AND_CONTINUE_OPTION_ID)).toBe(true);
    expect(isClearAndContinueOption("auto")).toBe(false);
  });

  it("only continues for the explicit clear-and-continue option", () => {
    const permission = makePermission({
      toolCall: { kind: "switch_mode" } as never,
    });
    expect(shouldContinueFromApprovedPlan(permission, "auto")).toBe(false);
    expect(
      shouldContinueFromApprovedPlan(permission, CLEAR_AND_CONTINUE_OPTION_ID),
    ).toBe(true);
    expect(
      shouldContinueFromApprovedPlan(permission, "reject_with_feedback"),
    ).toBe(false);
  });

  it("extracts trimmed plan markdown from rawInput", () => {
    const permission = makePermission({
      toolCall: {
        kind: "switch_mode",
        rawInput: { plan: "  ## Steps\n- one  " },
      } as never,
    });
    expect(extractPlanMarkdownFromPermission(permission)).toBe(
      "## Steps\n- one",
    );
    expect(
      extractPlanMarkdownFromPermission(
        makePermission({ toolCall: { kind: "switch_mode" } as never }),
      ),
    ).toBeNull();
  });

  it("maps approve option to execution mode", () => {
    expect(toApprovedExecutionMode("auto")).toBe("auto");
    expect(toApprovedExecutionMode("acceptEdits")).toBe("acceptEdits");
  });

  it("resolves clear-and-continue execution mode from answers", () => {
    expect(
      resolveClearAndContinueExecutionMode({ executionMode: "acceptEdits" }),
    ).toBe("acceptEdits");
    expect(resolveClearAndContinueExecutionMode({})).toBe("default");
    expect(resolveClearAndContinueExecutionMode()).toBe("default");
  });

  it("builds a continuation prompt that embeds the plan", () => {
    const blocks = buildApprovedPlanContinuationPrompt("## Fix\n- patch auth");
    expect(blocks).toHaveLength(1);
    expect(blocks[0]?.type).toBe("text");
    const textBlock = blocks[0];
    if (textBlock?.type !== "text") {
      throw new Error("expected text block");
    }
    expect(textBlock.text).toContain("## Fix\n- patch auth");
    expect(textBlock.text).toContain("execute this plan directly");
  });
});
