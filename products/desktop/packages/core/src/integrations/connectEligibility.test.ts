import { describe, expect, it } from "vitest";
import {
  computeShouldUseTeamFlow,
  validateInstallUrl,
} from "./connectEligibility";

describe("computeShouldUseTeamFlow", () => {
  it("is true only for admins on a project without a team integration in a known region", () => {
    expect(
      computeShouldUseTeamFlow({
        isAdmin: true,
        projectHasTeamIntegration: false,
        cloudRegion: "us",
      }),
    ).toBe(true);
  });

  it("is false for non-admins", () => {
    expect(
      computeShouldUseTeamFlow({
        isAdmin: false,
        projectHasTeamIntegration: false,
        cloudRegion: "us",
      }),
    ).toBe(false);
  });

  it("is false when the project already has a team integration", () => {
    expect(
      computeShouldUseTeamFlow({
        isAdmin: true,
        projectHasTeamIntegration: true,
        cloudRegion: "us",
      }),
    ).toBe(false);
  });

  it("is false when the cloud region is unknown", () => {
    expect(
      computeShouldUseTeamFlow({
        isAdmin: true,
        projectHasTeamIntegration: false,
        cloudRegion: null,
      }),
    ).toBe(false);
  });
});

describe("validateInstallUrl", () => {
  it("returns the trimmed url", () => {
    expect(validateInstallUrl("  https://x  ")).toBe("https://x");
  });

  it("throws when empty", () => {
    expect(() => validateInstallUrl("")).toThrow();
    expect(() => validateInstallUrl(null)).toThrow();
  });
});
