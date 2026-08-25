export type OnboardingStep =
  | "project-select"
  | "consent"
  | "connect-github"
  | "install-cli"
  | "select-repo";

export const ONBOARDING_STEPS: OnboardingStep[] = [
  "project-select",
  "consent",
  "connect-github",
  "install-cli",
  "select-repo",
];

export interface DetectedRepo {
  organization: string;
  repository: string;
  fullName: string;
  remote?: string;
  branch?: string;
}

export function computeActiveSteps(options: {
  /** Undefined while the integrations query is loading; the step only drops on a confirmed connection. */
  hasGithubIntegration: boolean | undefined;
  /** Undefined while the local git and gh checks are loading. */
  cliReady: boolean | undefined;
  /** Undefined until the project list has loaded, so a slow list cannot skip a real choice. */
  projectCount: number | undefined;
  consentRequired: boolean | undefined;
}): OnboardingStep[] {
  return ONBOARDING_STEPS.filter((step) => {
    if (step === "project-select" && options.projectCount === 1) return false;
    if (step === "consent" && options.consentRequired === false) return false;
    // Two independent reasons to skip: a GitHub integration means tasks run in
    // the cloud, and a ready local toolchain leaves the step nothing to offer.
    if (
      step === "install-cli" &&
      (options.hasGithubIntegration === true || options.cliReady === true)
    ) {
      return false;
    }
    return true;
  });
}

export function stepIndexOf(
  activeSteps: OnboardingStep[],
  step: OnboardingStep,
): number {
  return activeSteps.indexOf(step);
}

/**
 * Where to send the user when the step they are standing on drops out of
 * `activeSteps` (the conditional steps appear and disappear as their async
 * gates resolve). Prefers the next remaining step in canonical order — the
 * user was moving forward — and falls back to the closest earlier one, so a
 * vanishing step never resets progress to the start of the flow. Returns
 * `step` unchanged when it is still active, or when `activeSteps` is empty
 * (degenerate input: the flow always keeps at least the select-repo step).
 */
export function nearestActiveStep(
  activeSteps: OnboardingStep[],
  step: OnboardingStep,
): OnboardingStep {
  if (activeSteps.includes(step)) return step;
  const canonicalIndex = ONBOARDING_STEPS.indexOf(step);
  for (let i = canonicalIndex + 1; i < ONBOARDING_STEPS.length; i++) {
    const candidate = ONBOARDING_STEPS[i];
    if (activeSteps.includes(candidate)) return candidate;
  }
  for (let i = canonicalIndex - 1; i >= 0; i--) {
    const candidate = ONBOARDING_STEPS[i];
    if (activeSteps.includes(candidate)) return candidate;
  }
  return step;
}

export function isFirstStep(currentIndex: number): boolean {
  return currentIndex === 0;
}

export function isLastStep(
  activeSteps: OnboardingStep[],
  currentIndex: number,
): boolean {
  return currentIndex === activeSteps.length - 1;
}

export function nextStep(
  activeSteps: OnboardingStep[],
  currentIndex: number,
): OnboardingStep | null {
  if (isLastStep(activeSteps, currentIndex)) return null;
  return activeSteps[currentIndex + 1];
}

export function previousStep(
  activeSteps: OnboardingStep[],
  currentIndex: number,
): OnboardingStep | null {
  if (isFirstStep(currentIndex)) return null;
  return activeSteps[currentIndex - 1];
}

export function stepDirection(
  activeSteps: OnboardingStep[],
  currentIndex: number,
  target: OnboardingStep,
): 1 | -1 {
  const targetIndex = activeSteps.indexOf(target);
  return targetIndex >= currentIndex ? 1 : -1;
}
