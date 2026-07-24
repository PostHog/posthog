import { describe, expect, it } from "vitest";
import {
  deriveUpdateUiStatus,
  resolveMenuCheckFromStatus,
  resolveMenuCheckResult,
} from "./updateStore";

describe("deriveUpdateUiStatus", () => {
  it("hydrates an installing update", () => {
    expect(
      deriveUpdateUiStatus(
        { checking: false, updateReady: true, installing: true, version: "v2" },
        "idle",
      ),
    ).toEqual({ status: "installing", version: "v2" });
  });

  it("hydrates a ready update", () => {
    expect(
      deriveUpdateUiStatus(
        { checking: false, updateReady: true, version: "v2" },
        "idle",
      ),
    ).toEqual({ status: "ready", version: "v2" });
  });

  it("maps checking + downloading to downloading", () => {
    expect(
      deriveUpdateUiStatus({ checking: true, downloading: true }, "idle"),
    ).toEqual({
      status: "downloading",
      availableVersion: null,
      releaseNotes: null,
      releaseDate: null,
      downloadPercent: null,
      bytesPerSecond: null,
      downloadSizeBytes: null,
    });
  });

  it("hydrates an available update", () => {
    expect(
      deriveUpdateUiStatus(
        {
          checking: false,
          available: true,
          availableVersion: "v2",
          releaseNotes: "notes",
          releaseDate: "2026-01-01",
          downloadSizeBytes: 1234,
        },
        "idle",
      ),
    ).toEqual({
      status: "available",
      availableVersion: "v2",
      releaseNotes: "notes",
      releaseDate: "2026-01-01",
      downloadSizeBytes: 1234,
    });
  });

  it("defaults available fields to null when absent", () => {
    expect(
      deriveUpdateUiStatus({ checking: false, available: true }, "idle"),
    ).toEqual({
      status: "available",
      availableVersion: null,
      releaseNotes: null,
      releaseDate: null,
      downloadSizeBytes: null,
    });
  });

  it("maps checking to checking", () => {
    expect(deriveUpdateUiStatus({ checking: true }, "idle")).toEqual({
      status: "checking",
    });
  });

  it("resets to idle on upToDate when not ready/installing", () => {
    expect(
      deriveUpdateUiStatus({ checking: false, upToDate: true }, "checking"),
    ).toEqual({ status: "idle" });
  });

  it("does not reset a ready update on a stale upToDate status", () => {
    expect(
      deriveUpdateUiStatus({ checking: false, upToDate: true }, "ready"),
    ).toBeNull();
  });

  it("does not reset an installing update on a stale upToDate status", () => {
    expect(
      deriveUpdateUiStatus({ checking: false, upToDate: true }, "installing"),
    ).toBeNull();
  });
});

describe("resolveMenuCheckFromStatus", () => {
  it("returns null when no menu check is pending", () => {
    expect(
      resolveMenuCheckFromStatus({ checking: false, upToDate: true }, false),
    ).toBeNull();
  });

  it("returns a success toast on upToDate", () => {
    expect(
      resolveMenuCheckFromStatus({ checking: false, upToDate: true }, true),
    ).toEqual({
      clearPending: true,
      toast: { kind: "success", message: "You're on the latest version" },
    });
  });

  it("returns an error toast on error", () => {
    expect(
      resolveMenuCheckFromStatus({ checking: false, error: "boom" }, true),
    ).toEqual({
      clearPending: true,
      toast: {
        kind: "error",
        message: "Failed to check for updates",
        description: "boom",
      },
    });
  });

  it("suppresses the toast but clears pending when a check finishes with an update", () => {
    expect(resolveMenuCheckFromStatus({ checking: false }, true)).toEqual({
      clearPending: true,
    });
  });

  it("keeps pending while still checking", () => {
    expect(resolveMenuCheckFromStatus({ checking: true }, true)).toBeNull();
  });
});

describe("resolveMenuCheckResult", () => {
  it("returns null on success", () => {
    expect(resolveMenuCheckResult({ success: true })).toBeNull();
  });

  it("clears pending and shows error toast on disabled", () => {
    expect(
      resolveMenuCheckResult({
        success: false,
        errorCode: "disabled",
        errorMessage: "Updates only available in packaged builds",
      }),
    ).toEqual({
      clearPending: true,
      toast: {
        kind: "error",
        message: "Updates only available in packaged builds",
      },
    });
  });

  it("keeps pending on already_checking", () => {
    expect(
      resolveMenuCheckResult({ success: false, errorCode: "already_checking" }),
    ).toBeNull();
  });

  it("clears pending on unknown error codes", () => {
    expect(
      resolveMenuCheckResult({ success: false, errorCode: "future" }),
    ).toEqual({ clearPending: true });
  });
});
