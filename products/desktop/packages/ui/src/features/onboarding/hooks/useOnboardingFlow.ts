import {
  computeActiveSteps,
  isFirstStep as computeIsFirstStep,
  isLastStep as computeIsLastStep,
  nextStep as computeNextStep,
  previousStep as computePreviousStep,
  nearestActiveStep,
  type OnboardingStep,
  stepDirection,
  stepGatePending,
} from "@posthog/core/onboarding/steps";
import { useHostTRPC } from "@posthog/host-router/react";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useOrgConsent } from "@posthog/ui/features/consent/useOrgConsent";
import { useUserGithubIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  type ConsentRequirement,
  sampleConsentRequirement,
} from "./consentRequirement";

export function useOnboardingFlow() {
  const { localWorkspaces } = useHostCapabilities();
  const currentStep = useOnboardingStore((state) => state.currentStep);
  const setCurrentStep = useOnboardingStore((state) => state.setCurrentStep);
  const directionRef = useRef<1 | -1>(1);

  const { data: githubUserIntegrations, isPending: githubIntegrationsPending } =
    useUserGithubIntegrations();
  // The install-cli step only offers git and gh, so a ready toolchain skips it.
  // InstallCliStep reuses these cached results when the step does render.
  const trpc = useHostTRPC();
  // Cloud-only hosts serve no git procedures, and the CLI step is moot there.
  const { data: gitStatus } = useQuery(
    trpc.git.getGitStatus.queryOptions(undefined, {
      staleTime: 30_000,
      enabled: localWorkspaces,
    }),
  );
  const { data: ghStatus } = useQuery(
    trpc.git.getGhStatus.queryOptions(undefined, {
      staleTime: 30_000,
      enabled: localWorkspaces,
    }),
  );
  // Sampled on the first resolved check and held. Installing the tools while
  // standing on the step would otherwise drop it and advance the user mid-read.
  const [cliReady, setCliReady] = useState<boolean | undefined>(undefined);
  useEffect(() => {
    if (cliReady !== undefined) return;
    if (!localWorkspaces) {
      setCliReady(true);
      return;
    }
    if (gitStatus === undefined || ghStatus === undefined) return;
    setCliReady(
      gitStatus.installed && ghStatus.installed && ghStatus.authenticated,
    );
  }, [cliReady, localWorkspaces, gitStatus, ghStatus]);
  // Read the pending state, not the data: the query retries and then leaves
  // `data` undefined, which would hold the install-cli gate open for the rest
  // of the session. A failed lookup keeps the step, same as an unanswered one.
  const hasGithubIntegration = githubIntegrationsPending
    ? undefined
    : (githubUserIntegrations?.length ?? 0) > 0;
  // Counted off the store rather than through useProjects, whose auto-select
  // effect would then run in a second place and re-clear the query cache.
  const orgProjectsMap = useAuthStateValue((state) => state.orgProjectsMap);
  const hasDesktopAccess = useAuthStateValue(
    (state) =>
      state.desktopAccess.projectId === state.currentProjectId &&
      state.desktopAccess.status === "allowed",
  );
  // Anonymous bootstrap also reports fetched, with an empty map, so the count
  // has to wait for authentication or it settles the gate at zero before the
  // person signs in on the project-select card.
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const projectCount = useMemo(
    () =>
      isAuthenticated
        ? Object.values(orgProjectsMap).reduce(
            (total, org) => total + org.projects.length,
            0,
          )
        : undefined,
    [isAuthenticated, orgProjectsMap],
  );
  const consent = useOrgConsent(hasDesktopAccess);
  const consentSatisfied =
    consent.status === "resolved" ? consent.satisfied : undefined;
  const [consentRequirement, setConsentRequirement] =
    useState<ConsentRequirement>();

  useEffect(() => {
    if (consent.status !== "resolved") return;
    setConsentRequirement((current) =>
      sampleConsentRequirement(
        current,
        consent.organizationId,
        consent.needsAiConsent,
        consent.needsBetaTerms,
      ),
    );
  }, [consent]);

  // A failed lookup keeps the step, same as an unanswered one, but it answers
  // the gate. Otherwise the step shows with its view never recorded.
  const consentRequired =
    consent.status === "error"
      ? true
      : consentRequirement?.organizationId === consent.organizationId
        ? consentRequirement?.required
        : undefined;
  const sampledConsentRequirement =
    consentRequirement?.organizationId === consent.organizationId
      ? consentRequirement
      : undefined;

  const stepGates = useMemo(
    () => ({ hasGithubIntegration, cliReady, projectCount, consentRequired }),
    [hasGithubIntegration, cliReady, projectCount, consentRequired],
  );
  const activeSteps = useMemo(() => computeActiveSteps(stepGates), [stepGates]);

  useEffect(() => {
    if (!activeSteps.includes(currentStep)) {
      setCurrentStep(nearestActiveStep(activeSteps, currentStep));
    }
  }, [activeSteps, currentStep, setCurrentStep]);

  const currentIndex = activeSteps.indexOf(currentStep);
  const isFirstStep = computeIsFirstStep(currentIndex);
  const isLastStep = computeIsLastStep(activeSteps, currentIndex);

  const next = () => {
    const step = computeNextStep(activeSteps, currentIndex);
    if (step) {
      directionRef.current = 1;
      setCurrentStep(step);
    }
  };

  const back = () => {
    const step = computePreviousStep(activeSteps, currentIndex);
    if (step) {
      directionRef.current = -1;
      setCurrentStep(step);
    }
  };

  const goTo = (step: OnboardingStep) => {
    directionRef.current = stepDirection(activeSteps, currentIndex, step);
    setCurrentStep(step);
  };

  return {
    currentStep,
    currentIndex,
    currentStepPending: stepGatePending(currentStep, stepGates),
    totalSteps: activeSteps.length,
    activeSteps,
    isFirstStep,
    isLastStep,
    direction: directionRef.current,
    next,
    back,
    goTo,
    hasGithubIntegration,
    consentSatisfied,
    consentRequirement: sampledConsentRequirement,
  };
}
