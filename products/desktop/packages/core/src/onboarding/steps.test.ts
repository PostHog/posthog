import { describe, expect, it } from "vitest";
import {
  computeActiveSteps,
  isFirstStep,
  isLastStep,
  nearestActiveStep,
  nextStep,
  ONBOARDING_STEPS,
  type OnboardingStep,
  previousStep,
  stepDirection,
} from "./steps";

describe("computeActiveSteps", () => {
  it("drops invite-code when the user already has code access", () => {
    expect(computeActiveSteps(true, true)).not.toContain("invite-code");
  });

  it("keeps invite-code when access is unknown or false", () => {
    expect(computeActiveSteps(false, true)).toEqual(ONBOARDING_STEPS);
    expect(computeActiveSteps(null, true)).toEqual(ONBOARDING_STEPS);
    expect(computeActiveSteps(undefined, true)).toEqual(ONBOARDING_STEPS);
  });

  it("drops import-config when there is no importable config", () => {
    expect(computeActiveSteps(false, false)).not.toContain("import-config");
  });
});

describe("nearestActiveStep", () => {
  const withoutConditionals = computeActiveSteps(true, false);

  it("returns the step itself while it is still active", () => {
    expect(nearestActiveStep(ONBOARDING_STEPS, "import-config")).toBe(
      "import-config",
    );
  });

  it.each<{ removed: OnboardingStep; expected: OnboardingStep }>([
    // import-config vanished under the user: continue forward to select-repo,
    // not back to welcome (the regression that reset onboarding mid-flow).
    { removed: "import-config", expected: "select-repo" },
    { removed: "invite-code", expected: "connect-github" },
  ])(
    "moves forward to $expected when $removed drops out",
    ({ removed, expected }) => {
      expect(nearestActiveStep(withoutConditionals, removed)).toBe(expected);
    },
  );

  it("falls back to the closest earlier step when nothing follows", () => {
    const onlyEarlySteps: OnboardingStep[] = ["welcome", "project-select"];
    expect(nearestActiveStep(onlyEarlySteps, "import-config")).toBe(
      "project-select",
    );
  });

  it("returns the step itself when no steps are active", () => {
    expect(nearestActiveStep([], "import-config")).toBe("import-config");
  });
});

describe("step navigation", () => {
  const steps = computeActiveSteps(true, true);

  it("identifies first and last steps", () => {
    expect(isFirstStep(0)).toBe(true);
    expect(isFirstStep(1)).toBe(false);
    expect(isLastStep(steps, steps.length - 1)).toBe(true);
    expect(isLastStep(steps, 0)).toBe(false);
  });

  it("advances and retreats within bounds", () => {
    expect(nextStep(steps, 0)).toBe(steps[1]);
    expect(nextStep(steps, steps.length - 1)).toBeNull();
    expect(previousStep(steps, 1)).toBe(steps[0]);
    expect(previousStep(steps, 0)).toBeNull();
  });

  it("derives navigation direction", () => {
    expect(stepDirection(steps, 0, steps[2])).toBe(1);
    expect(stepDirection(steps, 2, steps[0])).toBe(-1);
    expect(stepDirection(steps, 1, steps[1])).toBe(1);
  });
});
