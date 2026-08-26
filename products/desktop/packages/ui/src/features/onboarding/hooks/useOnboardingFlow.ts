import {
  inferRepositoryProvider,
  toDetectedRepo,
} from "@posthog/core/onboarding/repoProvider";
import {
  computeActiveSteps,
  isFirstStep as computeIsFirstStep,
  isLastStep as computeIsLastStep,
  nextStep as computeNextStep,
  previousStep as computePreviousStep,
  type DetectedRepo,
  nearestActiveStep,
  type OnboardingStep,
  stepDirection,
  stepGatePending,
} from "@posthog/core/onboarding/steps";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import {
  useAuthStateFetched,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { useOrgConsent } from "@posthog/ui/features/consent/useOrgConsent";
import { useUserGithubIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useActiveRepoStore } from "@posthog/ui/shell/activeRepoStore";
import { track } from "@posthog/ui/shell/analytics";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type ConsentRequirement,
  sampleConsentRequirement,
} from "./consentRequirement";

export type { DetectedRepo };

export function useOnboardingFlow() {
  const hostClient = useHostTRPCClient();
  const { localWorkspaces } = useHostCapabilities();
  const currentStep = useOnboardingStore((state) => state.currentStep);
  const setCurrentStep = useOnboardingStore((state) => state.setCurrentStep);
  const selectedDirectory = useActiveRepoStore((state) => state.path);
  const setSelectedDirectory = useActiveRepoStore((state) => state.setPath);
  const setLastUsedCloudRepository = useSettingsStore(
    (state) => state.setLastUsedCloudRepository,
  );
  const directionRef = useRef<1 | -1>(1);

  const [detectedRepo, setDetectedRepo] = useState<DetectedRepo | null>(null);
  const [isDetectingRepo, setIsDetectingRepo] = useState(false);
  const hasRehydrated = useRef(false);

  useEffect(() => {
    // Cloud-only hosts have no local git to detect against.
    if (!localWorkspaces) return;
    if (hasRehydrated.current || !selectedDirectory) return;
    hasRehydrated.current = true;
    setIsDetectingRepo(true);
    hostClient.git.detectRepo
      .query({ directoryPath: selectedDirectory })
      .then((result) => setDetectedRepo(toDetectedRepo(result)))
      .catch(() => {})
      .finally(() => setIsDetectingRepo(false));
  }, [selectedDirectory, hostClient, localWorkspaces]);

  const [selectedCloudRepo, setSelectedCloudRepo] = useState<string | null>(
    null,
  );
  const handleCloudRepoChange = useCallback(
    (repo: string | null) => {
      setSelectedCloudRepo(repo);
      setLastUsedCloudRepository(repo);
      if (repo) {
        setSelectedDirectory("");
        setDetectedRepo(null);
        track(ANALYTICS_EVENTS.ONBOARDING_FOLDER_SELECTED, {
          has_git_remote: true,
          repository_provider: "github",
        });
      }
    },
    [setLastUsedCloudRepository, setSelectedDirectory],
  );

  const handleDirectoryChange = useCallback(
    async (path: string) => {
      setSelectedDirectory(path);
      setDetectedRepo(null);

      // Cloud-only: `path` is a remote "owner/repo" reference. Persist it as the
      // last-used cloud repository so the task input prefills it.
      if (!localWorkspaces) {
        setLastUsedCloudRepository(path || null);
        track(ANALYTICS_EVENTS.ONBOARDING_FOLDER_SELECTED, {
          has_git_remote: !!path,
          repository_provider: "github",
        });
        return;
      }

      setSelectedCloudRepo(null);
      setLastUsedCloudRepository(null);

      if (!path) return;

      setIsDetectingRepo(true);
      try {
        const result = await hostClient.git.detectRepo.query({
          directoryPath: path,
        });
        const repo = toDetectedRepo(result);
        setDetectedRepo(repo);
        track(ANALYTICS_EVENTS.ONBOARDING_FOLDER_SELECTED, {
          has_git_remote: !!repo,
          repository_provider: repo
            ? inferRepositoryProvider(repo.remote)
            : "local",
        });
      } catch {
        track(ANALYTICS_EVENTS.ONBOARDING_FOLDER_SELECTED, {
          has_git_remote: false,
          repository_provider: "local",
        });
      } finally {
        setIsDetectingRepo(false);
      }
    },
    [
      setSelectedDirectory,
      setLastUsedCloudRepository,
      hostClient,
      localWorkspaces,
    ],
  );

  const { data: githubUserIntegrations } = useUserGithubIntegrations();
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
  const hasGithubIntegration = githubUserIntegrations
    ? githubUserIntegrations.length > 0
    : undefined;
  // Counted off the store rather than through useProjects, whose auto-select
  // effect would then run in a second place and re-clear the query cache.
  const orgProjectsMap = useAuthStateValue((state) => state.orgProjectsMap);
  const hasDesktopAccess = useAuthStateValue(
    (state) =>
      state.desktopAccess.projectId === state.currentProjectId &&
      state.desktopAccess.status === "allowed",
  );
  const authFetched = useAuthStateFetched();
  const projectCount = useMemo(
    () =>
      authFetched
        ? Object.values(orgProjectsMap).reduce(
            (total, org) => total + org.projects.length,
            0,
          )
        : undefined,
    [authFetched, orgProjectsMap],
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
    selectedDirectory,
    detectedRepo,
    isDetectingRepo,
    handleDirectoryChange,
    selectedCloudRepo,
    handleCloudRepoChange,
    hasGithubIntegration,
    consentSatisfied,
    consentRequirement: sampledConsentRequirement,
  };
}
