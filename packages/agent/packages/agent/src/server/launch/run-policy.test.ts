import { describe, expect, it } from "vitest";
import { parseServerRunPolicy } from "./run-policy";
import policyCases from "./run-policy-cases.json";

const RUN_ID = "run-1";
const SERVER_POLICY = {
  ...policyCases.policy_from_origin[0].expected,
  run_id: RUN_ID,
};

describe("run policy", () => {
  it.each(policyCases.policy_from_origin)(
    "reads the policy the server resolves for $name",
    ({ expected }) => {
      const parsed = parseServerRunPolicy(
        JSON.stringify({ ...expected, run_id: RUN_ID }),
      );

      expect(parsed?.policy).toEqual({
        finishTool: expected.finish_tool,
        finishReportRequired: expected.finish_report_required,
        reportActivityTool: expected.report_activity_tool,
        expectsSystemPrompt: expected.expects_system_prompt,
        threadLink: expected.thread_link,
        defaultClientProvenance:
          expected.default_client_provenance ?? undefined,
        billingProduct: undefined,
      });
    },
  );

  it("reads a server policy that carries fields it does not know", () => {
    const parsed = parseServerRunPolicy(
      JSON.stringify({ ...SERVER_POLICY, future_field: true }),
    );

    expect([parsed?.runId, parsed?.policy.threadLink]).toEqual([RUN_ID, true]);
  });

  it.each<[string, unknown, string | undefined]>([
    ["a product it knows", "workflows", "workflows"],
    ["a product it does not know", "future_product", undefined],
    ["no product", undefined, undefined],
  ])("reads the billing product from %s", (_, billing_product, expected) => {
    const parsed = parseServerRunPolicy(
      JSON.stringify({ ...SERVER_POLICY, billing_product }),
    );

    expect([parsed?.policy.billingProduct, parsed?.policy.threadLink]).toEqual([
      expected,
      true,
    ]);
  });

  it.each<[string, string]>([
    ["malformed JSON", "{"],
    ["a missing field", JSON.stringify({ finish_tool: true })],
    [
      "a field of the wrong type",
      JSON.stringify({ ...SERVER_POLICY, finish_tool: "yes" }),
    ],
    ["a value that is not an object", "true"],
    ["no run id", JSON.stringify({ ...SERVER_POLICY, run_id: undefined })],
  ])("rejects a server policy with %s", (_, raw) => {
    expect(parseServerRunPolicy(raw)).toBeUndefined();
  });
});
