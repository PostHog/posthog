import { describe, expect, it } from "vitest";
import { GITHUB_CONNECT_TIMEOUT_MESSAGE } from "../integrations/connectErrors";
import {
  buildConnectFailedProps,
  buildConnectFailureFingerprint,
  buildInstallationSettingsUrl,
  deriveAlternativeConnectedProjects,
  deriveConnectButtonState,
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

  it("falls through timeout, connecting, then default", () => {
    const base = {
      hasConnectError: false,
      connectErrorMessage: "",
    };
    expect(
      getGithubPanelMessage({ ...base, timedOut: true, isConnecting: false }),
    ).toBe(GITHUB_CONNECT_TIMEOUT_MESSAGE);
    expect(
      getGithubPanelMessage({ ...base, timedOut: false, isConnecting: true }),
    ).toBe("Waiting for GitHub...");
    expect(
      getGithubPanelMessage({ ...base, timedOut: false, isConnecting: false }),
    ).toMatch(/Unlocks cloud runs/);
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

describe("deriveConnectButtonState", () => {
  it("is a fresh connect when idle", () => {
    expect(
      deriveConnectButtonState({
        isConnecting: false,
        hasConnectError: false,
        timedOut: false,
      }),
    ).toEqual({ isRetry: false, shouldReset: false, label: "Connect GitHub" });
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
