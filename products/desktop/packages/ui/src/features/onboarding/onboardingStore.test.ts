import { describe, expect, it } from "vitest";
import { migrateOnboardingState } from "./onboardingStore";

describe("migrateOnboardingState", () => {
  it("moves a persisted invite-code step forward", () => {
    const migrated = migrateOnboardingState({
      currentStep: "invite-code",
      hasCompletedOnboarding: false,
      hasShippedFirstPr: false,
      selectedProjectId: 1,
    });

    expect(migrated.currentStep).toBe("consent");
  });
});
