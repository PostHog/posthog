import { describe, expect, it } from "vitest";
import { E2E } from "./config";

/**
 * Fail-loud precondition for the live e2e suite. Without POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY every
 * arm self-skips and `vitest run` exits 0 — a green run that tested nothing. This
 * one non-skipped test turns a missing token into a RED run.
 */
describe("live e2e preconditions", () => {
  it("requires POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY (else the suite would skip-to-green)", () => {
    expect(
      E2E.hasToken,
      "POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY is not set — every adapter arm would skip and the run " +
        "would pass without testing anything. Mint one via e2e/run-e2e.sh or " +
        "set POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY against a reachable POSTHOG_CODE_E2E_GATEWAY_URL.",
    ).toBe(true);
  });

  // On CI the localhost default can never work, so an unset gateway URL means
  // every model turn dies with ConnectionRefused — 8 scattered failures instead
  // of this one clear one.
  it("requires an explicit POSTHOG_CODE_E2E_GATEWAY_URL on CI when a token is set", () => {
    if (!process.env.CI || !E2E.hasToken) return;
    expect(
      process.env.POSTHOG_CODE_E2E_GATEWAY_URL,
      "POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY is set but " +
        "POSTHOG_CODE_E2E_GATEWAY_URL is empty — on CI the suite would fall " +
        "back to localhost:3308 (unreachable from a runner) and every model " +
        "turn would fail with ConnectionRefused. Set the org variable to a " +
        "runner-reachable gateway.",
    ).toBeTruthy();
  });

  // When a token is present, the codex arm must not skip silently — a missing
  // binary would let the run pass with zero codex coverage.
  it("requires the native codex binary when a token is set (else codex skips-to-green)", () => {
    if (!E2E.hasToken) return; // no token → whole suite skips; nothing to guard
    expect(
      E2E.skipReason("codex"),
      "POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY is set but the native codex binary is missing — the " +
        "codex arm would silently skip and the run would pass without exercising " +
        "the codex adapter. Ensure apps/code/scripts/download-binaries.mjs ran.",
    ).toBeNull();
  });
});
