import { describe, expect, it } from "vitest";
import {
  CONNECT_INITIAL_STATUS,
  connectReducer,
  deriveConnectFlags,
  githubInvalidationKeys,
  slackInvalidationKeys,
  toConnectError,
} from "./connectMachine";

describe("connectReducer", () => {
  it("begin clears error and moves to connecting", () => {
    expect(
      connectReducer(
        { state: "error", error: { message: "x", code: null } },
        { type: "begin" },
      ),
    ).toEqual({ state: "connecting", error: null });
  });

  it("fail records the error", () => {
    const error = { message: "boom", code: "x" };
    expect(
      connectReducer(CONNECT_INITIAL_STATUS, { type: "fail", error }),
    ).toEqual({ state: "error", error });
  });

  it("succeed and reset return to idle", () => {
    expect(
      connectReducer(CONNECT_INITIAL_STATUS, { type: "succeed" }).state,
    ).toBe("idle");
    expect(
      connectReducer(CONNECT_INITIAL_STATUS, { type: "reset" }).state,
    ).toBe("idle");
  });

  it("timeout preserves the existing error", () => {
    const status = {
      state: "error" as const,
      error: { message: "e", code: null },
    };
    expect(connectReducer(status, { type: "timeout" })).toEqual({
      state: "timed-out",
      error: status.error,
    });
  });
});

describe("deriveConnectFlags", () => {
  it("derives boolean flags from state", () => {
    expect(deriveConnectFlags("connecting")).toEqual({
      isConnecting: true,
      isTimedOut: false,
      hasError: false,
    });
    expect(deriveConnectFlags("error").hasError).toBe(true);
    expect(deriveConnectFlags("timed-out").isTimedOut).toBe(true);
  });
});

describe("toConnectError", () => {
  it("uses the error message when given an Error", () => {
    expect(toConnectError(new Error("nope"), "fallback")).toEqual({
      message: "nope",
      code: null,
    });
  });

  it("falls back for non-Error values", () => {
    expect(toConnectError("x", "fallback").message).toBe("fallback");
  });
});

describe("invalidation keys", () => {
  it("omits the project key when projectId is null", () => {
    expect(githubInvalidationKeys(null)).toEqual([
      ["integrations", "list"],
      ["user-github-integrations"],
      ["github_login"],
    ]);
  });

  it("includes the project key when projectId is set", () => {
    expect(githubInvalidationKeys(7)[0]).toEqual(["integrations", 7]);
  });

  it("slack keys cover list and root", () => {
    expect(slackInvalidationKeys()).toEqual([
      ["integrations", "list"],
      ["integrations"],
    ]);
  });
});
