import { describe, expect, it } from "vitest";
import { GITHUB_CONNECT_TIMEOUT_MESSAGE } from "../integrations/connectErrors";
import {
  buildConnectAbandonedProps,
  buildConnectFailedProps,
  buildConnectFailureFingerprint,
  buildInstallationSettingsUrl,
  deriveAlternativeConnectedProjects,
  deriveConnectButtonState,
  deriveGithubApprovalState,
  getGithubPanelMessage,
  isAnyIntegrationStale,
  resolveSelectedProjectId,
} from "./githubConnectPanel";

describe("getGithubPanelMessage", () => {
  it("prioritizes the connect error message", () => {
    expect(
      getGithubPanelMessage({
        hasConnectError: true,
        connectErrorMessage: "boom",
        timedOut: false,
        isConnecting: false,
      }),
    ).toBe("boom");
  });

  it("reports a timeout, and nothing while connecting or idle", () => {
    const base = {
      hasConnectError: false,
      connectErrorMessage: "",
    };
    expect(
      getGithubPanelMessage({ ...base, timedOut: true, isConnecting: false }),
    ).toBe(GITHUB_CONNECT_TIMEOUT_MESSAGE);
    expect(
      getGithubPanelMessage({ ...base, timedOut: false, isConnecting: true }),
    ).toBeNull();
    expect(
      getGithubPanelMessage({ ...base, timedOut: false, isConnecting: false }),
    ).toBeNull();
  });
});

describe("resolveSelectedProjectId", () => {
  const projects = [{ id: 7 }, { id: 8 }];

  it("prefers the manual selection", () => {
    expect(resolveSelectedProjectId(3, 5, projects)).toBe(3);
  });

  it("falls back to current project then first project then null", () => {
    expect(resolveSelectedProjectId(null, 5, projects)).toBe(5);
    expect(resolveSelectedProjectId(null, null, projects)).toBe(7);
    expect(resolveSelectedProjectId(null, null, [])).toBeNull();
  });
});

describe("deriveAlternativeConnectedProjects", () => {
  const projects = [{ id: 1 }, { id: 2 }, { id: 3 }];

  it("is empty when the user already has a personal integration", () => {
    expect(deriveAlternativeConnectedProjects(true, projects, 1)).toEqual([]);
  });

  it("excludes the selected project", () => {
    expect(
      deriveAlternativeConnectedProjects(false, projects, 2).map((p) => p.id),
    ).toEqual([1, 3]);
  });
});

describe("isAnyIntegrationStale", () => {
  it("detects a failed installation", () => {
    const integrations = [{ installation_id: "a" }, { installation_id: "b" }];
    expect(isAnyIntegrationStale(integrations, ["b"])).toBe(true);
    expect(isAnyIntegrationStale(integrations, ["z"])).toBe(false);
  });
});

describe("buildInstallationSettingsUrl", () => {
  it("links an org install to the app page (org settings are owner-only)", () => {
    expect(
      buildInstallationSettingsUrl(
        { type: "Organization", name: "acme" },
        "42",
      ),
    ).toBe("https://github.com/apps/posthog");
  });

  it("matches the organization account type case-insensitively", () => {
    expect(
      buildInstallationSettingsUrl(
        { type: "organization", name: "acme" },
        "42",
      ),
    ).toBe("https://github.com/apps/posthog");
  });

  it("builds a personal settings url otherwise", () => {
    expect(buildInstallationSettingsUrl({ type: "User" }, "42")).toBe(
      "https://github.com/settings/installations/42",
    );
    expect(buildInstallationSettingsUrl(null, "42")).toBe(
      "https://github.com/settings/installations/42",
    );
  });
});

describe("buildConnectFailureFingerprint", () => {
  it("is null when there is no failure", () => {
    expect(
      buildConnectFailureFingerprint({
        hasConnectError: false,
        timedOut: false,
        errorCode: null,
      }),
    ).toBeNull();
  });

  it("prefers timeout over error code", () => {
    expect(
      buildConnectFailureFingerprint({
        hasConnectError: true,
        timedOut: true,
        errorCode: "bad",
      }),
    ).toBe("timeout");
  });

  it("uses the error code, falling back to error", () => {
    expect(
      buildConnectFailureFingerprint({
        hasConnectError: true,
        timedOut: false,
        errorCode: "bad",
      }),
    ).toBe("bad");
    expect(
      buildConnectFailureFingerprint({
        hasConnectError: true,
        timedOut: false,
        errorCode: null,
      }),
    ).toBe("error");
  });
});

describe("buildConnectFailedProps", () => {
  it("maps timeout to a timeout reason without an error type", () => {
    expect(
      buildConnectFailedProps({
        hasConnectError: false,
        timedOut: true,
        errorCode: "ignored",
      }),
    ).toEqual({ reason: "timeout", error_type: "ignored" });
  });

  it("maps error to an error reason carrying the code", () => {
    expect(
      buildConnectFailedProps({
        hasConnectError: true,
        timedOut: false,
        errorCode: "bad",
      }),
    ).toEqual({ reason: "error", error_type: "bad" });
    expect(
      buildConnectFailedProps({
        hasConnectError: true,
        timedOut: false,
        errorCode: null,
      }),
    ).toEqual({ reason: "error", error_type: undefined });
  });
});

describe("buildConnectAbandonedProps", () => {
  it("carries the flow type and rounds the elapsed seconds", () => {
    expect(
      buildConnectAbandonedProps({
        flowType: "user_new",
        startedAtMs: 1_000,
        nowMs: 1_000 + 12_400,
      }),
    ).toEqual({ flow_type: "user_new", seconds_since_started: 12 });
  });

  it("never reports a negative duration", () => {
    expect(
      buildConnectAbandonedProps({
        flowType: "team_existing",
        startedAtMs: 10_000,
        nowMs: 1_000,
      }),
    ).toEqual({ flow_type: "team_existing", seconds_since_started: 0 });
  });
});

describe("deriveConnectButtonState", () => {
  it("is a fresh connect when idle", () => {
    expect(
      deriveConnectButtonState({
        isConnecting: false,
        hasConnectError: false,
        timedOut: false,
      }),
    ).toEqual({
      isRetry: false,
      shouldReset: false,
      label: "Sign in with GitHub",
    });
  });

  it("labels a retry on error and asks to reset", () => {
    expect(
      deriveConnectButtonState({
        isConnecting: false,
        hasConnectError: true,
        timedOut: false,
      }),
    ).toEqual({ isRetry: true, shouldReset: true, label: "Try again" });
  });

  it("labels retry connection while connecting", () => {
    expect(
      deriveConnectButtonState({
        isConnecting: true,
        hasConnectError: false,
        timedOut: true,
      }),
    ).toEqual({ isRetry: true, shouldReset: false, label: "Retry connection" });
  });
});

describe("deriveGithubApprovalState", () => {
  it.each([
    [
      "this attempt just came back pending",
      "github_install_pending",
      [],
      false,
      "awaiting",
    ],
    [
      "a pending request row exists server-side",
      null,
      [{ status: "pending" }],
      false,
      "awaiting",
    ],
    [
      "an approved request exists but no integration is linked yet",
      null,
      [{ status: "approved" }],
      false,
      "approved",
    ],
    [
      "an existing integration wins over a stale approved row",
      null,
      [{ status: "approved" }],
      true,
      "none",
    ],
    [
      "an existing integration wins over a stale pending row",
      null,
      [{ status: "pending" }],
      true,
      "none",
    ],
    ["nothing pending or approved", null, [], false, "none"],
  ] as const)("%s", (_label, errorCode, requests, hasIntegration, expected) => {
    expect(
      deriveGithubApprovalState({
        errorCode,
        requests: [...requests],
        hasIntegration,
      }),
    ).toBe(expected);
  });
});
