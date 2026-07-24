import { describe, expect, it } from "vitest";
import {
  classifyGatewayLimitError,
  getErrorMessage,
  isAuthError,
  isFatalSessionError,
  isNotAuthenticatedError,
  isRateLimitError,
  isTransientUpstreamError,
  NotAuthenticatedError,
  serializeError,
} from "./errors";

describe("NotAuthenticatedError", () => {
  it("has the expected name and a default message", () => {
    const err = new NotAuthenticatedError();
    expect(err.name).toBe("NotAuthenticatedError");
    expect(err.message).toBe("Not authenticated");
  });

  it("accepts a custom message", () => {
    expect(new NotAuthenticatedError("token gone").message).toBe("token gone");
  });
});

describe("isNotAuthenticatedError", () => {
  it("recognises a real NotAuthenticatedError", () => {
    expect(isNotAuthenticatedError(new NotAuthenticatedError())).toBe(true);
  });

  it("recognises a structurally tagged object", () => {
    expect(isNotAuthenticatedError({ name: "NotAuthenticatedError" })).toBe(
      true,
    );
  });

  it("rejects a plain Error and non-objects", () => {
    expect(isNotAuthenticatedError(new Error("nope"))).toBe(false);
    expect(isNotAuthenticatedError(null)).toBe(false);
    expect(isNotAuthenticatedError("NotAuthenticatedError")).toBe(false);
  });
});

describe("getErrorMessage", () => {
  it("reads the message from an Error", () => {
    expect(getErrorMessage(new Error("boom"))).toBe("boom");
  });

  it("reads the message from a message-bearing object", () => {
    expect(getErrorMessage({ message: 42 })).toBe("42");
  });

  it("returns an empty string for valueless inputs", () => {
    expect(getErrorMessage(null)).toBe("");
    expect(getErrorMessage("just a string")).toBe("");
  });
});

describe("isAuthError", () => {
  it.each([
    "Authentication required",
    "Failed to authenticate",
    "authentication_error",
    "authentication_failed",
    "Access token has expired",
  ])("matches the auth pattern in %j (case-insensitive)", (message) => {
    expect(isAuthError(new Error(message))).toBe(true);
  });

  it("returns false for unrelated and empty errors", () => {
    expect(isAuthError(new Error("disk full"))).toBe(false);
    expect(isAuthError(null)).toBe(false);
  });
});

describe("isRateLimitError", () => {
  it("matches rate-limit patterns in the message or the details", () => {
    expect(isRateLimitError("Rate limit exceeded")).toBe(true);
    expect(isRateLimitError("oops", "rate_limit hit")).toBe(true);
    expect(isRateLimitError("server said [429]")).toBe(true);
  });

  it("returns false when neither message nor details match", () => {
    expect(isRateLimitError("network down", "timeout")).toBe(false);
  });
});

describe("classifyGatewayLimitError", () => {
  it.each([
    [
      // The gate 403 as the ACP layer surfaces it (full body embedded).
      `Internal error: API Error: 403 {"error":{"message":"Model 'claude-opus-4-8' needs a paid PostHog plan. Models available on the free tier: @cf/zai-org/glm-5.2. Add a payment method to your organization to unlock all models. (rate_limit)","type":"permission_error","code":"model_gate"}}`,
      "model_gate",
    ],
    [
      // SDK surfaces that reduce the body to its message string.
      "API Error: 403 Model 'gpt-5.5' needs a paid PostHog plan. (rate_limit)",
      "model_gate",
    ],
    [
      // Bare FastAPI detail from gateways predating the error envelope.
      `Internal error: API Error: 403 {"detail":"Model 'claude-opus-4-8' needs a paid PostHog plan."}`,
      "model_gate",
    ],
    [
      "Rate limit exceeded: Your team has reached its PostHog Code usage limit for this billing period. See https://app.posthog.com/organization/billing for your usage and limits.",
      "org_limit",
    ],
    [
      // Gateway fallback wording for a credit bucket without a mapped message.
      "Your team has reached its usage limit for this billing period.",
      "org_limit",
    ],
    [
      // Per-user free valves fire only for unsubscribed orgs; the modal's
      // subscribed bit picks the free-tier copy.
      "Rate limit exceeded: User burst rate limit exceeded",
      "org_limit",
    ],
    ["Rate limit exceeded: User sustained rate limit exceeded", "org_limit"],
  ])("classifies %j as %s", (message, expected) => {
    expect(classifyGatewayLimitError(message)).toBe(expected);
  });

  it("matches against the details when the message is generic", () => {
    expect(
      classifyGatewayLimitError(
        "Internal error",
        "API Error: 403 Model 'gpt-5.5' needs a paid PostHog plan.",
      ),
    ).toBe("model_gate");
  });

  it.each([
    "Rate limit exceeded",
    "Rate limit exceeded: Product rate limit exceeded",
    "Your team has used its monthly PostHog AI credits.",
    "network down",
  ])("returns null for %j", (message) => {
    expect(classifyGatewayLimitError(message)).toBeNull();
  });
});

describe("isFatalSessionError", () => {
  it.each([
    "internal error",
    "process exited",
    "session did not end",
    "not ready for writing",
    "session not found",
  ])("treats %j as fatal", (message) => {
    expect(isFatalSessionError(message)).toBe(true);
  });

  it("does not treat a rate-limit error as fatal even if a fatal phrase is present", () => {
    expect(isFatalSessionError("process exited", "rate limit exceeded")).toBe(
      false,
    );
  });

  it("returns false for ordinary recoverable errors", () => {
    expect(isFatalSessionError("temporary network blip")).toBe(false);
  });

  it.each([
    "Internal error: API Error: the operation timed out",
    "Internal error: API Error: Request timeout",
    "Internal error: API Error: terminated",
    "Internal error: API Error: Connection error",
    "Internal error: API Error: 529 overloaded_error",
  ])("does not treat the transient upstream failure %j as fatal", (message) => {
    expect(isFatalSessionError(message)).toBe(false);
  });

  it("does not treat a transient upstream failure in the details as fatal", () => {
    expect(
      isFatalSessionError(
        "internal error",
        "API Error: the operation timed out",
      ),
    ).toBe(false);
  });

  it("does not treat a free-tier model-gate 403 as fatal despite the Internal error wrapper", () => {
    // Shim-less body (no "(rate_limit)" suffix), so this exercises the
    // model-gate exclusion rather than the rate-limit one.
    expect(
      isFatalSessionError(
        `Internal error: API Error: 403 {"detail":"Model 'claude-opus-4-8' needs a paid PostHog plan."}`,
      ),
    ).toBe(false);
  });
});

describe("isTransientUpstreamError", () => {
  it.each([
    "API Error: the operation timed out",
    "API Error: terminated",
    "API Error: Connection error",
    "API Error: 500 internal server error",
    "API Error: 529 overloaded_error",
    "Internal error: API Error: request timed out",
    "Internal error: API Error: Connection closed mid-response. The response above may be incomplete.",
    "The socket connection was closed unexpectedly.",
    "socket connection closed",
  ])("recognises %j", (message) => {
    expect(isTransientUpstreamError(message)).toBe(true);
  });

  it("matches against the details when the message is generic", () => {
    expect(
      isTransientUpstreamError(
        "Internal error",
        "API Error: the operation timed out",
      ),
    ).toBe(true);
  });

  it.each([
    "process exited",
    "session not found",
    "the operation timed out", // no "API Error:" marker — not an upstream turn failure
    "API Error: 400 invalid_request_error",
  ])("does not match %j", (message) => {
    expect(isTransientUpstreamError(message)).toBe(false);
  });
});

describe("serializeError", () => {
  it("captures name, message and code from an Error", () => {
    const err = Object.assign(new TypeError("boom"), { code: "ERR_X" });
    expect(serializeError(err)).toEqual({
      name: "TypeError",
      message: "boom",
      code: "ERR_X",
    });
  });

  it("walks the cause chain (the undici 'terminated' shape)", () => {
    const cause = Object.assign(new Error("other side closed"), {
      code: "UND_ERR_SOCKET",
    });
    const err = new TypeError("terminated", { cause });
    expect(serializeError(err)).toEqual({
      name: "TypeError",
      message: "terminated",
      cause: {
        name: "Error",
        message: "other side closed",
        code: "UND_ERR_SOCKET",
      },
    });
  });

  it("bounds depth to avoid runaway or cyclic chains", () => {
    const cyclic: { message: string; cause?: unknown } = { message: "a" };
    cyclic.cause = cyclic;
    const result = serializeError(cyclic, 2);
    expect(result.cause?.cause?.message).toBe("a");
    expect(result.cause?.cause?.cause).toBeUndefined();
  });

  it("handles non-Error inputs", () => {
    expect(serializeError("plain string")).toEqual({ message: "plain string" });
    expect(serializeError(42)).toEqual({ message: "42" });
    expect(serializeError(null)).toEqual({ message: "null" });
  });

  it("captures a numeric code", () => {
    expect(serializeError({ message: "x", code: 42 })).toEqual({
      message: "x",
      code: 42,
    });
  });

  it("does not follow the cause chain at maxDepth 0", () => {
    const err = new Error("top", { cause: new Error("inner") });
    expect(serializeError(err, 0)).toEqual({ name: "Error", message: "top" });
  });

  it("omits name for a plain object without one", () => {
    expect(serializeError({ message: "foo", code: "ENOENT" })).toEqual({
      message: "foo",
      code: "ENOENT",
    });
  });

  it("returns only name and message for a bare Error", () => {
    expect(serializeError(new Error("x"))).toEqual({
      name: "Error",
      message: "x",
    });
  });
});
