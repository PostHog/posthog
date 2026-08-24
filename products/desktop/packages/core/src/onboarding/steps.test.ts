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

const allSteps = {
  hasCodeAccess: false,
  hasImportableConfig: true,
  hasGithubIntegration: undefined,
  projectCount: 2,
  consentRequired: true,
};

describe("computeActiveSteps", () => {
  it("drops invite-code when the user already has code access", () => {
    expect(
      computeActiveSteps({ ...allSteps, hasCodeAccess: true }),
    ).not.toContain("invite-code");
  });

  it("keeps invite-code when access is unknown or false", () => {
    expect(computeActiveSteps(allSteps)).toEqual(ONBOARDING_STEPS);
    expect(computeActiveSteps({ ...allSteps, hasCodeAccess: null })).toEqual(
      ONBOARDING_STEPS,
    );
    expect(
      computeActiveSteps({ ...allSteps, hasCodeAccess: undefined }),
    ).toEqual(ONBOARDING_STEPS);
  });

  it("drops import-config when there is no importable config", () => {
    expect(
      computeActiveSteps({ ...allSteps, hasImportableConfig: false }),
    ).not.toContain("import-config");
  });

  it("drops project-select only when there is exactly one project", () => {
    expect(computeActiveSteps({ ...allSteps, projectCount: 1 })).not.toContain(
      "project-select",
    );
    expect(computeActiveSteps({ ...allSteps, projectCount: 2 })).toContain(
      "project-select",
    );
    expect(
      computeActiveSteps({ ...allSteps, projectCount: undefined }),
    ).toContain("project-select");
    expect(computeActiveSteps({ ...allSteps, projectCount: 0 })).toContain(
      "project-select",
    );
  });

  it("drops install-cli only on a confirmed github connection", () => {
    expect(
      computeActiveSteps({ ...allSteps, hasGithubIntegration: true }),
    ).not.toContain("install-cli");
    expect(
      computeActiveSteps({ ...allSteps, hasGithubIntegration: false }),
    ).toContain("install-cli");
    expect(computeActiveSteps(allSteps)).toContain("install-cli");
  });

  it("includes consent from the sampled requirement", () => {
    expect(ONBOARDING_STEPS.indexOf("consent")).toBe(
      ONBOARDING_STEPS.indexOf("invite-code") + 1,
    );
    expect(
      computeActiveSteps({ ...allSteps, consentRequired: undefined }),
    ).toContain("consent");
    expect(
      computeActiveSteps({ ...allSteps, consentRequired: false }),
    ).not.toContain("consent");
  });
});

describe("nearestActiveStep", () => {
  const withoutConditionals = computeActiveSteps({
    hasCodeAccess: true,
    hasImportableConfig: false,
    hasGithubIntegration: undefined,
    projectCount: 2,
    consentRequired: true,
  });

  it("returns the step itself while it is still active", () => {
    expect(nearestActiveStep(ONBOARDING_STEPS, "import-config")).toBe(
      "import-config",
    );
  });

  it.each<{ removed: OnboardingStep; expected: OnboardingStep }>([
    // import-config vanished under the user: continue forward to select-repo,
    // not back to welcome (the regression that reset onboarding mid-flow).
    { removed: "import-config", expected: "select-repo" },
    { removed: "invite-code", expected: "consent" },
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
  const steps = computeActiveSteps({
    hasCodeAccess: true,
    hasImportableConfig: true,
    hasGithubIntegration: undefined,
    projectCount: 2,
    consentRequired: true,
  });

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
