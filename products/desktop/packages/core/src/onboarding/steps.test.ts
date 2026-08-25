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

type StepGates = Parameters<typeof computeActiveSteps>[0];

const allSteps: StepGates = {
  hasGithubIntegration: undefined,
  cliReady: undefined,
  projectCount: 2,
  consentRequired: true,
};

describe("computeActiveSteps", () => {
  it("keeps every step while no gate has resolved against it", () => {
    expect(computeActiveSteps(allSteps)).toEqual(ONBOARDING_STEPS);
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

  it.each<{ name: string; options: Partial<StepGates> }>([
    {
      name: "a confirmed github connection",
      options: { hasGithubIntegration: true },
    },
    { name: "a ready local toolchain", options: { cliReady: true } },
  ])("drops install-cli on $name", ({ options }) => {
    expect(computeActiveSteps({ ...allSteps, ...options })).not.toContain(
      "install-cli",
    );
  });

  it("keeps install-cli until a skip reason is confirmed", () => {
    expect(computeActiveSteps(allSteps)).toContain("install-cli");
    expect(
      computeActiveSteps({
        ...allSteps,
        hasGithubIntegration: false,
        cliReady: false,
      }),
    ).toContain("install-cli");
  });

  it("includes consent from the sampled requirement", () => {
    expect(ONBOARDING_STEPS.indexOf("consent")).toBe(
      ONBOARDING_STEPS.indexOf("project-select") + 1,
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
    hasGithubIntegration: true,
    cliReady: undefined,
    projectCount: 2,
    consentRequired: true,
  });

  it("returns the step itself while it is still active", () => {
    expect(nearestActiveStep(ONBOARDING_STEPS, "install-cli")).toBe(
      "install-cli",
    );
  });

  it.each<{ removed: OnboardingStep; expected: OnboardingStep }>([
    // install-cli vanished under the user: continue forward to select-repo,
    // not back to the start (the regression that reset onboarding mid-flow).
    { removed: "install-cli", expected: "select-repo" },
  ])(
    "moves forward to $expected when $removed drops out",
    ({ removed, expected }) => {
      expect(nearestActiveStep(withoutConditionals, removed)).toBe(expected);
    },
  );

  it("falls back to the closest earlier step when nothing follows", () => {
    const onlyEarlySteps: OnboardingStep[] = ["project-select", "consent"];
    expect(nearestActiveStep(onlyEarlySteps, "select-repo")).toBe("consent");
  });

  it("returns the step itself when no steps are active", () => {
    expect(nearestActiveStep([], "select-repo")).toBe("select-repo");
  });
});

describe("step navigation", () => {
  const steps = computeActiveSteps({
    hasGithubIntegration: undefined,
    cliReady: undefined,
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
