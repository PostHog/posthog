export type OnboardingStep =
  | "welcome"
  | "project-select"
  | "invite-code"
  | "connect-github"
  | "install-cli"
  | "import-config"
  | "select-repo";

export const ONBOARDING_STEPS: OnboardingStep[] = [
  "welcome",
  "project-select",
  "invite-code",
  "connect-github",
  "install-cli",
  "import-config",
  "select-repo",
];

export interface DetectedRepo {
  organization: string;
  repository: string;
  fullName: string;
  remote?: string;
  branch?: string;
}

export function computeActiveSteps(
  hasCodeAccess: boolean | null | undefined,
  hasImportableConfig: boolean,
): OnboardingStep[] {
  return ONBOARDING_STEPS.filter((step) => {
    if (step === "invite-code" && hasCodeAccess === true) return false;
    if (step === "import-config" && !hasImportableConfig) return false;
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
 * (degenerate input: the flow always keeps at least the welcome step).
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
