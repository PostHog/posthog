import { describe, expect, it } from "vitest";
import { type RunPolicy, runPolicyFromOrigin } from "./run-policy";
import policyCases from "./run-policy-cases.json";

function toWire(policy: RunPolicy): Record<string, unknown> {
  return {
    finish_tool: policy.finishTool,
    finish_report_required: policy.finishReportRequired,
    report_activity_tool: policy.reportActivityTool,
    branch_push_only: policy.branchPushOnly,
    expects_system_prompt: policy.expectsSystemPrompt,
    thread_link: policy.threadLink,
    default_client_provenance: policy.defaultClientProvenance ?? null,
  };
}

describe("runPolicyFromOrigin", () => {
  it.each(policyCases.policy_from_origin)(
    "resolves $name",
    ({ origin_product, end_run_when_done, caller_ends_run, expected }) => {
      const policy = runPolicyFromOrigin({
        originProduct: origin_product,
        endRunWhenDone: end_run_when_done,
        callerEndsRun: caller_ends_run,
      });

      expect(toWire(policy)).toEqual(expected);
    },
  );

  it.each<[string, string | null, boolean, boolean]>([
    ["an unknown origin", null, false, false],
    ["an empty origin", "", false, false],
    ["an unknown origin with the end-run opt-in", null, true, true],
  ])(
    "decides the finish tool for %s",
    (_, originProduct, endRunWhenDone, expected) => {
      const policy = runPolicyFromOrigin({
        originProduct,
        endRunWhenDone,
        callerEndsRun: false,
      });

      expect([policy.finishTool, policy.finishReportRequired]).toEqual([
        expected,
        false,
      ]);
    },
  );
});
