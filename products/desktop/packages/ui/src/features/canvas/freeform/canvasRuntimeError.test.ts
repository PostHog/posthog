import { describe, expect, it } from "vitest";
import { canvasRuntimeErrorAnalytics } from "./canvasRuntimeError";

describe("canvasRuntimeErrorAnalytics", () => {
  it("captures only the CSP directive", () => {
    expect(
      canvasRuntimeErrorAnalytics("SecurityPolicyViolationError: img-src"),
    ).toEqual({
      error_type: "SecurityPolicyViolationError",
      csp_directive: "img-src",
    });
  });

  it("does not capture arbitrary runtime messages", () => {
    expect(
      canvasRuntimeErrorAnalytics(
        "TypeError: request failed with secret@example.com",
      ),
    ).toEqual({ error_type: "TypeError" });
  });
});
