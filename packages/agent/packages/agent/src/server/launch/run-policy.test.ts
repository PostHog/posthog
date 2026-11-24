import { describe, expect, it } from "vitest";
import { parseServerRunPolicy, runPolicyFromOrigin } from "./run-policy";
import policyCases from "./run-policy-cases.json";

const RUN_ID = "run-1";
const SERVER_POLICY = {
  ...policyCases.policy_from_origin[0].expected,
  run_id: RUN_ID,
};

describe("run policy", () => {
  it.each(policyCases.policy_from_origin)(
    "resolves $name from its origin as the server does",
    ({ origin_product, end_run_when_done, caller_ends_run, expected }) => {
      const policy = runPolicyFromOrigin({
        originProduct: origin_product,
        endRunWhenDone: end_run_when_done,
        callerEndsRun: caller_ends_run,
      });

      expect(policy).toEqual(
        parseServerRunPolicy(JSON.stringify({ ...expected, run_id: RUN_ID }))
          ?.policy,
      );
    },
  );

  it("reads a server policy that carries fields it does not know", () => {
    const parsed = parseServerRunPolicy(
      JSON.stringify({ ...SERVER_POLICY, billing_product: "posthog_code" }),
    );

    expect([parsed?.runId, parsed?.policy.threadLink]).toEqual([RUN_ID, true]);
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
