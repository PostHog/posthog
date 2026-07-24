import { describe, expect, it } from "vitest";
import {
  computeAutoRetryFinalState,
  OFFLINE_SESSION_MESSAGE,
  routeLocalConnect,
} from "./connectRouting";

describe("routeLocalConnect", () => {
  it("routes to no-auth when auth is missing", () => {
    expect(
      routeLocalConnect({
        hasAuth: false,
        latestRunId: "run-1",
        latestRunLogUrl: "https://logs/run-1",
      }),
    ).toEqual({ kind: "no-auth" });
  });

  it("routes to resume-existing when run id and log url are present", () => {
    expect(
      routeLocalConnect({
        hasAuth: true,
        latestRunId: "run-1",
        latestRunLogUrl: "https://logs/run-1",
      }),
    ).toEqual({
      kind: "resume-existing",
      taskRunId: "run-1",
      logUrl: "https://logs/run-1",
    });
  });

  it("routes to create-new when there is no prior run", () => {
    expect(routeLocalConnect({ hasAuth: true })).toEqual({
      kind: "create-new",
    });
  });

  it("routes to create-new when run id exists but log url is missing", () => {
    expect(routeLocalConnect({ hasAuth: true, latestRunId: "run-1" })).toEqual({
      kind: "create-new",
    });
  });

  it("routes to create-new when log url exists but run id is missing", () => {
    expect(
      routeLocalConnect({
        hasAuth: true,
        latestRunLogUrl: "https://logs/run-1",
      }),
    ).toEqual({ kind: "create-new" });
  });
});

describe("computeAutoRetryFinalState", () => {
  it("returns a disconnected offline state when the device went offline", () => {
    expect(
      computeAutoRetryFinalState({
        wentOffline: true,
        lastRetryMessage: "boom",
        originalMessage: "first boom",
      }),
    ).toEqual({
      status: "disconnected",
      errorTitle: undefined,
      errorMessage: OFFLINE_SESSION_MESSAGE,
    });
  });

  it("returns an error state with the last retry message when still online", () => {
    expect(
      computeAutoRetryFinalState({
        wentOffline: false,
        lastRetryMessage: "retry boom",
        originalMessage: "first boom",
      }),
    ).toEqual({
      status: "error",
      errorTitle: "Failed to connect",
      errorMessage: "retry boom",
    });
  });

  it("falls back to the original message when no retry message is set", () => {
    expect(
      computeAutoRetryFinalState({
        wentOffline: false,
        lastRetryMessage: "",
        originalMessage: "first boom",
      }),
    ).toEqual({
      status: "error",
      errorTitle: "Failed to connect",
      errorMessage: "first boom",
    });
  });
});
