import type { SignalReport } from "@posthog/shared/types";
import { describe, expect, it } from "vitest";
import { computeRefundEligibility } from "./refundEligibility";

function report(overrides: Partial<SignalReport> = {}): SignalReport {
  return {
    id: "report-1",
    title: "Some report",
    implementation_pr_url: "https://github.com/PostHog/posthog/pull/1",
    refund: null,
    billing_exempt_reason: null,
    refund_ineligibility_reason: null,
    ...overrides,
  } as unknown as SignalReport;
}

describe("computeRefundEligibility", () => {
  it.each([
    ["no implementation PR hides the button", { implementation_pr_url: null }],
    [
      "an already-refunded report hides the button",
      { refund: { id: "r1", reason: "other" } } as Partial<SignalReport>,
    ],
    [
      "a billing-exempt report hides the button",
      { billing_exempt_reason: "free" },
    ],
  ])("%s", (_label, overrides) => {
    const result = computeRefundEligibility(report(overrides));
    expect(result.canRefund).toBe(false);
    expect(result.disabledReason).toBeNull();
  });

  it("offers the button for a billable, unrefunded PR", () => {
    const result = computeRefundEligibility(report());
    expect(result.canRefund).toBe(true);
    expect(result.disabledReason).toBeNull();
  });

  it.each([
    [
      "out_of_period",
      "This PR was billed in a previous billing period and can no longer be refunded.",
    ],
    ["no_billable_pr", "This PR isn't billable, so there's nothing to refund."],
  ])(
    "surfaces backend ineligibility copy for %s while keeping the button visible",
    (reason, copy) => {
      const result = computeRefundEligibility(
        report({ refund_ineligibility_reason: reason }),
      );
      expect(result.canRefund).toBe(true);
      expect(result.disabledReason).toBe(copy);
    },
  );

  it("falls back to generic copy for an unrecognized ineligibility reason", () => {
    const result = computeRefundEligibility(
      report({ refund_ineligibility_reason: "some_new_backend_reason" }),
    );
    expect(result.canRefund).toBe(true);
    expect(result.disabledReason).toBe("This PR can't be refunded right now.");
  });

  it("ignores an ineligibility reason when the button is hidden anyway", () => {
    const result = computeRefundEligibility(
      report({
        implementation_pr_url: null,
        refund_ineligibility_reason: "out_of_period",
      }),
    );
    expect(result.canRefund).toBe(false);
    expect(result.disabledReason).toBeNull();
  });
});
