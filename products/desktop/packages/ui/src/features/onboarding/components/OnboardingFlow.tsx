import {
  ArrowLeft,
  ArrowRight,
  CheckCircle,
  Lifebuoy,
  SignOut,
} from "@phosphor-icons/react";
import { getAuthIdentity } from "@posthog/core/auth/authIdentity";
import { integrationKeys } from "@posthog/core/integrations/repositoryKeys";
import {
  classifyIntegrations,
  type Integration,
} from "@posthog/core/integrations/selectors";
import {
  buildAbandonedProps,
  buildCompletedProps,
  buildStepCompletedProps,
  type StepCompletedContext,
} from "@posthog/core/onboarding/analytics";
import {
  planSpaceRepoAssignments,
  resolveRepoIntegrationId,
} from "@posthog/core/onboarding/spaceRepoAssignment";
import {
  Button,
  ButtonGroup,
  Item,
  ItemActions,
  ItemContent,
  ItemMedia,
  ItemTitle,
  Text,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { TaskChannel } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useLogoutMutation } from "@posthog/ui/features/auth/useAuthMutations";
import {
  AUTH_SCOPED_QUERY_META,
  useCurrentUser,
} from "@posthog/ui/features/auth/useCurrentUser";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { ConsentStep } from "@posthog/ui/features/consent/ConsentStep";
import { useUserGithubIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { ConnectGitHubStep } from "@posthog/ui/features/onboarding/components/ConnectGitHubStep";
import { InstallCliStep } from "@posthog/ui/features/onboarding/components/InstallCliStep";
import { useOnboardingFlow } from "@posthog/ui/features/onboarding/hooks/useOnboardingFlow";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { shipIt } from "@posthog/ui/primitives/confetti";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import { ProductWordmark } from "@posthog/ui/primitives/ProductWordmark";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { firstRun } from "@posthog/ui/shell/firstRun";
import { logger } from "@posthog/ui/shell/logger";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { isMac, isWindows } from "@posthog/ui/utils/platform";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { ProjectSelectStep } from "./ProjectSelectStep";
import { SelectRepoStep } from "./SelectRepoStep";

const IS_DEV = import.meta.env.DEV;

const log = logger.scope("onboarding-flow");

const stepVariants = {
  enter: (dir: number) => ({ opacity: 0, x: dir * 20 }),
  center: { opacity: 1, x: 0 },
  exit: (dir: number) => ({ opacity: 0, x: dir * -20 }),
};

interface OnboardingFlowProps {
  onOpenSupport?: () => void;
}

function OnboardingAccount({
  email,
  isAuthenticated,
  isLoggingOut,
  onLogout,
}: {
  email?: string;
  isAuthenticated: boolean;
  isLoggingOut: boolean;
  onLogout: () => void;
}) {
  if (!isAuthenticated) return null;

  return (
    <aside className="absolute right-8 bottom-6 z-[2] w-[380px] max-w-[calc(100%-4rem)]">
      <Item
        variant="muted"
        size="sm"
        className="w-full border border-border py-1"
      >
        <ItemMedia variant="icon">
          <CheckCircle size={14} weight="fill" className="text-(--green-11)" />
        </ItemMedia>
        <ItemContent>
          <ItemTitle className="max-w-full truncate font-normal text-xs">
            Signed in as {email ?? "your PostHog account"}
          </ItemTitle>
        </ItemContent>
        <ItemActions>
          <Button
            size="xs"
            variant="link-muted"
            className="min-h-11"
            onClick={onLogout}
            loading={isLoggingOut}
          >
            <SignOut size={14} />
            Log out
          </Button>
        </ItemActions>
      </Item>
    </aside>
  );
}

function OnboardingDebugNavigation({
  currentIndex,
  totalSteps,
  onBack,
  onNext,
}: {
  currentIndex: number;
  totalSteps: number;
  onBack: () => void;
  onNext: () => void;
}) {
  if (!IS_DEV) return null;

  return (
    <nav
      aria-label="Onboarding debug navigation"
      className="no-drag flex items-center gap-2"
    >
      <ButtonGroup aria-label="Onboarding step navigation">
        <Button
          size="icon-sm"
          variant="outline"
          aria-label="Previous onboarding step"
          disabled={currentIndex <= 0}
          onClick={onBack}
        >
          <ArrowLeft size={12} />
        </Button>
        <Button
          size="icon-sm"
          variant="outline"
          aria-label="Next onboarding step"
          disabled={currentIndex < 0 || currentIndex >= totalSteps - 1}
          onClick={onNext}
        >
          <ArrowRight size={12} />
        </Button>
      </ButtonGroup>
      <Text size="xs" variant="muted">
        {currentIndex + 1} / {totalSteps}
      </Text>
    </nav>
  );
}

function OnboardingHeader({
  currentIndex,
  totalSteps,
  onBack,
  onNext,
  onOpenSupport,
  onSkip,
  showSkipSetup,
}: {
  currentIndex: number;
  totalSteps: number;
  onBack: () => void;
  onNext: () => void;
  onOpenSupport?: () => void;
  onSkip: () => void;
  showSkipSetup: boolean;
}) {
  return (
    <header
      className="flex h-10 w-full items-center gap-3"
      style={{
        paddingLeft: isMac ? "env(titlebar-area-x, 78px)" : "78px",
        paddingRight: isWindows ? "140px" : "12px",
      }}
    >
      <div className="no-drag [&_p]:!text-md [&_svg]:!h-[18px] [&_svg]:!w-auto flex items-center">
        <ProductWordmark />
      </div>
      <OnboardingDebugNavigation
        currentIndex={currentIndex}
        totalSteps={totalSteps}
        onBack={onBack}
        onNext={onNext}
      />
      <div className="no-drag ml-auto flex items-center gap-1">
        <Button
          size="xs"
          variant="link-muted"
          className="min-h-8 px-2 text-xs opacity-80 hover:opacity-100"
          onClick={onOpenSupport}
        >
          <Lifebuoy size={12} />
          Get support
        </Button>
        {showSkipSetup && (
          <Button
            size="xs"
            variant="link-muted"
            className="min-h-8 px-2 text-xs opacity-80 hover:opacity-100"
            onClick={onSkip}
          >
            Skip setup
            <ArrowRight size={12} weight="bold" />
          </Button>
        )}
      </div>
    </header>
  );
}

export function OnboardingFlow({ onOpenSupport }: OnboardingFlowProps) {
  const [consentSubmitting, setConsentSubmitting] = useState(false);
  const queryClient = useQueryClient();
  const {
    currentStep,
    currentIndex,
    activeSteps,
    direction,
    next,
    back,
    selectedDirectory,
    detectedRepo,
    isDetectingRepo,
    handleDirectoryChange,
    selectedCloudRepo,
    handleCloudRepoChange,
    hasGithubIntegration,
    consentSatisfied,
    consentRequirement,
  } = useOnboardingFlow();
  const completeOnboarding = useOnboardingStore(
    (state) => state.completeOnboarding,
  );
  const resetOnboarding = useOnboardingStore((state) => state.resetOnboarding);
  const logoutMutation = useLogoutMutation();
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const { data: githubUserIntegrations = [] } = useUserGithubIntegrations();
  const setLastUsedWorkspaceMode = useSettingsStore(
    (state) => state.setLastUsedWorkspaceMode,
  );
  const apiClient = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client: apiClient });
  const { localWorkspaces } = useHostCapabilities();
  const startupIdentity = useAuthStateValue(getAuthIdentity);

  // Best-effort. The response also seeds the channel cache that the first-run
  // landing reads moments later.
  const assignRepoToSpaces = async (): Promise<void> => {
    if (!apiClient || !startupIdentity) return;
    const provisioned = await firstRun(startupIdentity, apiClient).provisioned;
    if (!provisioned) return;
    // Set before the entry exists: setQueryData builds the query from the defaults in
    // place at that moment, and an unmarked entry survives clearAuthScopedQueries and
    // hands the next account these channels. Every mounted read of this key is already
    // auth-scoped via useAuthenticatedQuery; this covers the one write that precedes them.
    queryClient.setQueryDefaults(TASK_CHANNELS_QUERY_KEY, {
      meta: AUTH_SCOPED_QUERY_META,
    });
    queryClient.setQueryData(TASK_CHANNELS_QUERY_KEY, provisioned.channels);
    // Cloud-only hosts keep the picked GitHub repo in selectedDirectory (they
    // never set selectedCloudRepo). On local-workspace hosts selectedDirectory
    // can be a filesystem path, so only the explicit cloud pick is a valid
    // "owner/repo" space default there.
    const cloudRepo = localWorkspaces
      ? selectedCloudRepo
      : selectedDirectory || null;
    if (!cloudRepo) return;
    // Fetched directly: the integrations store only fills once the main app's
    // hooks mount, which has not happened during onboarding.
    const integrations = await queryClient.fetchQuery({
      queryKey: integrationKeys.list(),
      queryFn: () => apiClient.getIntegrations() as Promise<Integration[]>,
      staleTime: 60_000,
      meta: AUTH_SCOPED_QUERY_META,
    });
    const integrationId = resolveRepoIntegrationId(
      cloudRepo,
      classifyIntegrations(integrations).githubIntegrations,
    );
    // Channels only accept a team integration alongside repositories, so a
    // user-level-only GitHub connection cannot set a space default.
    if (integrationId == null) return;
    for (const channelId of planSpaceRepoAssignments(provisioned.channels, {
      personalCreated: provisioned.personal_created,
      generalCreated: provisioned.general_created,
    })) {
      const updated = await apiClient.updateTaskChannelRepositories(
        channelId,
        integrationId,
        [cloudRepo],
      );
      // The direct API call bypasses the standard mutation's cache sync, so
      // patch the seeded channel cache with the assigned repository. Otherwise
      // consumers stay on the repository-less provision response until the poll.
      queryClient.setQueryData<TaskChannel[]>(
        TASK_CHANNELS_QUERY_KEY,
        (channels) =>
          channels?.map((channel) =>
            channel.id === updated.id ? updated : channel,
          ),
      );
    }
  };

  const flowStartedAtRef = useRef(Date.now());
  const stepEnteredAtRef = useRef(Date.now());

  // biome-ignore lint/correctness/useExhaustiveDependencies: fires once on mount; subsequent step views fire from handleNext/handleBack
  useEffect(() => {
    track(ANALYTICS_EVENTS.ONBOARDING_STARTED);
    track(ANALYTICS_EVENTS.ONBOARDING_STEP_VIEWED, {
      step_id: currentStep,
      step_index: currentIndex,
      total_steps: activeSteps.length,
    });
  }, []);

  useEffect(() => {
    const handleBeforeUnload = () => {
      track(
        ANALYTICS_EVENTS.ONBOARDING_ABANDONED,
        buildAbandonedProps({
          lastStepId: currentStep,
          flowStartedAtMs: flowStartedAtRef.current,
          nowMs: Date.now(),
        }),
      );
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [currentStep]);

  const trackStepCompleted = (context?: StepCompletedContext) => {
    track(
      ANALYTICS_EVENTS.ONBOARDING_STEP_COMPLETED,
      buildStepCompletedProps({
        stepId: currentStep,
        stepIndex: currentIndex,
        totalSteps: activeSteps.length,
        stepEnteredAtMs: stepEnteredAtRef.current,
        nowMs: Date.now(),
        context,
      }),
    );
  };

  const trackStepViewed = (stepIndex: number) => {
    const stepId = activeSteps[stepIndex];
    if (!stepId) return;
    track(ANALYTICS_EVENTS.ONBOARDING_STEP_VIEWED, {
      step_id: stepId,
      step_index: stepIndex,
      total_steps: activeSteps.length,
    });
    stepEnteredAtRef.current = Date.now();
  };

  const handleNext = (context?: StepCompletedContext) => {
    if (
      currentStep === "consent" &&
      (consentSatisfied !== true || consentSubmitting)
    ) {
      return;
    }
    // `onClick={onNext}` would pass the click event here; a DOM event spread
    // into capture properties poisons the whole analytics batch.
    const safeContext =
      context && "nativeEvent" in context ? undefined : context;
    trackStepCompleted(safeContext);
    trackStepViewed(currentIndex + 1);
    next();
  };

  const handleBack = () => {
    if (currentStep === "consent" && consentSubmitting) return;
    trackStepViewed(currentIndex - 1);
    back();
  };

  // The first active step has nowhere to go back to, and which step that is
  // shifts as the conditional steps resolve.
  const onBack = currentIndex <= 0 ? undefined : handleBack;

  useHotkeys("right", () => handleNext(), { enableOnFormTags: false }, [
    handleNext,
  ]);
  useHotkeys("left", handleBack, { enableOnFormTags: false }, [handleBack]);

  const handleComplete = (repoSkipped: boolean) => {
    if (repoSkipped) {
      track(ANALYTICS_EVENTS.ONBOARDING_STEP_SKIPPED, {
        step_id: currentStep,
        step_index: currentIndex,
        reason: "no_repo_selected",
      });
    } else {
      trackStepCompleted();
    }
    track(
      ANALYTICS_EVENTS.ONBOARDING_COMPLETED,
      buildCompletedProps({
        flowStartedAtMs: flowStartedAtRef.current,
        nowMs: Date.now(),
        githubConnected: githubUserIntegrations.length > 0,
        repoSkipped,
      }),
    );
    if (githubUserIntegrations.length > 0) {
      // GitHub connected defaults the run mode to cloud (overriding a local
      // mode left behind by an earlier session), but an explicit local folder
      // pick in this step must win over that default. On cloud-only hosts
      // selectedDirectory holds an "owner/repo" value, not a local path, so
      // only treat it as a local pick on local-workspace hosts.
      const pickedLocalRepo =
        localWorkspaces && !selectedCloudRepo && !!selectedDirectory;
      setLastUsedWorkspaceMode(pickedLocalRepo ? "local" : "cloud");
    }
    assignRepoToSpaces().catch((error) =>
      log.warn("Failed to save onboarding repo to spaces", { error }),
    );
    shipIt();
    completeOnboarding();
    openTaskInput();
  };

  const handleSkip = () => {
    track(ANALYTICS_EVENTS.ONBOARDING_STEP_SKIPPED, {
      step_id: currentStep,
      step_index: currentIndex,
      reason: "dev_skip",
    });
    completeOnboarding();
    openTaskInput();
  };

  const handleLogout = () => {
    track(
      ANALYTICS_EVENTS.ONBOARDING_ABANDONED,
      buildAbandonedProps({
        lastStepId: currentStep,
        flowStartedAtMs: flowStartedAtRef.current,
        nowMs: Date.now(),
      }),
    );
    logoutMutation.mutate();
    resetOnboarding();
  };

  return (
    <FullScreenLayout
      backgroundPattern="grid"
      showFooter={false}
      titleBarContent={
        <OnboardingHeader
          currentIndex={currentIndex}
          totalSteps={activeSteps.length}
          onBack={back}
          onNext={next}
          onOpenSupport={onOpenSupport}
          onSkip={handleSkip}
          showSkipSetup={IS_DEV && isAuthenticated}
        />
      }
    >
      <OnboardingAccount
        email={currentUser?.email}
        isAuthenticated={isAuthenticated}
        isLoggingOut={logoutMutation.isPending}
        onLogout={handleLogout}
      />
      <div className="h-full overflow-y-auto px-8 pt-16">
        <div className="mx-auto flex min-h-full w-full max-w-[720px] flex-col items-center">
          <div className="w-full">
            <div aria-hidden="true" className="h-16 shrink-0" />
            <AnimatePresence mode="wait" custom={direction}>
              {currentStep === "project-select" && (
                <motion.div
                  key="project-select"
                  custom={direction}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  variants={stepVariants}
                  transition={{ duration: 0.3 }}
                  className="w-full"
                >
                  <ProjectSelectStep onNext={handleNext} onBack={onBack} />
                </motion.div>
              )}

              {currentStep === "consent" && (
                <motion.div
                  key="consent"
                  custom={direction}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  variants={stepVariants}
                  transition={{ duration: 0.3 }}
                  className="w-full"
                >
                  <ConsentStep
                    onNext={handleNext}
                    onBack={onBack}
                    requirements={consentRequirement}
                    onSubmittingChange={setConsentSubmitting}
                  />
                </motion.div>
              )}

              {currentStep === "connect-github" && (
                <motion.div
                  key="connect-github"
                  custom={direction}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  variants={stepVariants}
                  transition={{ duration: 0.3 }}
                  className="w-full"
                >
                  <ConnectGitHubStep onNext={handleNext} onBack={onBack} />
                </motion.div>
              )}

              {currentStep === "install-cli" && (
                <motion.div
                  key="install-cli"
                  custom={direction}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  variants={stepVariants}
                  transition={{ duration: 0.3 }}
                  className="w-full"
                >
                  <InstallCliStep onNext={handleNext} onBack={handleBack} />
                </motion.div>
              )}

              {currentStep === "select-repo" && (
                <motion.div
                  key="select-repo"
                  custom={direction}
                  initial="enter"
                  animate="center"
                  exit="exit"
                  variants={stepVariants}
                  transition={{ duration: 0.3 }}
                  className="w-full"
                >
                  <SelectRepoStep
                    onComplete={handleComplete}
                    onBack={handleBack}
                    selectedDirectory={selectedDirectory}
                    detectedRepo={detectedRepo}
                    isDetectingRepo={isDetectingRepo}
                    onDirectoryChange={handleDirectoryChange}
                    selectedCloudRepo={selectedCloudRepo}
                    onCloudRepoChange={handleCloudRepoChange}
                    hasGithubIntegration={hasGithubIntegration}
                  />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </FullScreenLayout>
  );
}
