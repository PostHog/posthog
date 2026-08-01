import type {
  OnboardingAbandonedProperties,
  OnboardingCompletedProperties,
  OnboardingStepCompletedProperties,
  OnboardingStepId,
} from "@posthog/shared/analytics-events";

export function durationSeconds(startedAtMs: number, nowMs: number): number {
  return Math.round((nowMs - startedAtMs) / 1000);
}

export type StepCompletedContext = Omit<
  OnboardingStepCompletedProperties,
  "step_id" | "step_index" | "total_steps" | "duration_seconds"
>;

export function buildStepCompletedProps(opts: {
  stepId: OnboardingStepId;
  stepIndex: number;
  totalSteps: number;
  stepEnteredAtMs: number;
  nowMs: number;
  context?: StepCompletedContext;
}): OnboardingStepCompletedProperties {
  return {
    step_id: opts.stepId,
    step_index: opts.stepIndex,
    total_steps: opts.totalSteps,
    duration_seconds: durationSeconds(opts.stepEnteredAtMs, opts.nowMs),
    ...opts.context,
  };
}

export function buildCompletedProps(opts: {
  flowStartedAtMs: number;
  nowMs: number;
  githubConnected: boolean;
  repoSkipped: boolean;
}): OnboardingCompletedProperties {
  return {
    duration_seconds: durationSeconds(opts.flowStartedAtMs, opts.nowMs),
    github_connected: opts.githubConnected,
    repo_skipped: opts.repoSkipped,
  };
}

export function buildAbandonedProps(opts: {
  lastStepId: OnboardingStepId;
  flowStartedAtMs: number;
  nowMs: number;
}): OnboardingAbandonedProperties {
  return {
    last_step_id: opts.lastStepId,
    duration_seconds: durationSeconds(opts.flowStartedAtMs, opts.nowMs),
  };
}
