import { describe, expect, it } from "vitest";
import {
  type CheckForUpdatesResult,
  type CheckResultAction,
  deriveUpdateStatus,
  resolveCheckResultAction,
} from "./updateStatus";

describe("deriveUpdateStatus", () => {
  it("reports downloading", () => {
    expect(deriveUpdateStatus({ checking: true, downloading: true })).toEqual({
      message: "Downloading update...",
      type: "info",
      checking: true,
    });
  });

  it("reports up to date", () => {
    expect(deriveUpdateStatus({ checking: false, upToDate: true })).toEqual({
      message: "You're on the latest version",
      type: "success",
      checking: false,
    });
  });

  it("reports an update ready with a version", () => {
    expect(
      deriveUpdateStatus({
        checking: false,
        updateReady: true,
        version: "1.2.3",
      }),
    ).toEqual({
      message: "Update 1.2.3 ready to install",
      type: "success",
      checking: false,
    });
  });

  it("reports an update ready without a version", () => {
    expect(deriveUpdateStatus({ checking: false, updateReady: true })).toEqual({
      message: "Update ready to install",
      type: "success",
      checking: false,
    });
  });

  it("reports an available update with a version", () => {
    expect(
      deriveUpdateStatus({
        checking: false,
        available: true,
        availableVersion: "1.2.3",
      }),
    ).toEqual({
      message: "Update 1.2.3 available",
      type: "success",
      checking: false,
    });
  });

  it("reports an available update without a version", () => {
    expect(deriveUpdateStatus({ checking: false, available: true })).toEqual({
      message: "Update available",
      type: "success",
      checking: false,
    });
  });

  it("reports a check error", () => {
    expect(
      deriveUpdateStatus({
        checking: false,
        error: "Update check timed out. Please try again.",
      }),
    ).toEqual({
      message: "Update check timed out. Please try again.",
      type: "error",
      checking: false,
    });
  });

  it("clears checking when finished with no other signal", () => {
    expect(deriveUpdateStatus({ checking: false })).toEqual({
      checking: false,
    });
  });

  it("returns empty while still checking", () => {
    expect(deriveUpdateStatus({ checking: true })).toEqual({});
  });
});

describe("resolveCheckResultAction", () => {
  it.each<[string, CheckForUpdatesResult, CheckResultAction | null]>([
    ["success lets the subscription own the status", { success: true }, null],
    [
      "a check already in progress",
      { success: false, errorCode: "already_checking" },
      null,
    ],
    [
      "disabled with a reason",
      {
        success: false,
        errorCode: "disabled",
        errorMessage: "Updates only available in packaged builds",
      },
      {
        updatesDisabled: true,
        message: "Updates only available in packaged builds",
        type: "error",
      },
    ],
    [
      "disabled without a reason falls back",
      { success: false, errorCode: "disabled" },
      {
        updatesDisabled: true,
        message: "Failed to check for updates",
        type: "error",
      },
    ],
    [
      "a generic failure without a message",
      { success: false },
      {
        updatesDisabled: false,
        message: "Failed to check for updates",
        type: "error",
      },
    ],
  ])("resolves %s", (_label, result, expected) => {
    expect(resolveCheckResultAction(result)).toEqual(expected);
  });
});
