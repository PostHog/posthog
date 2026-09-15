import {
  ArrowLeft,
  ArrowRight,
  CheckCircle,
  Lifebuoy,
  SignOut,
} from "@phosphor-icons/react";
import {
  buildAbandonedProps,
  buildCompletedProps,
  buildStepCompletedProps,
  type StepCompletedContext,
} from "@posthog/core/onboarding/analytics";
import type { OnboardingStep } from "@posthog/core/onboarding/steps";
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
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useLogoutMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
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
import { isMac, isWindows } from "@posthog/ui/utils/platform";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { ProjectSelectStep } from "./ProjectSelectStep";

const IS_DEV = import.meta.env.DEV;

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
          <CheckCircle
            size={14}
            weight="fill"
            className="text-success-foreground"
          />
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
  const [isCompleting, setIsCompleting] = useState(false);
  const {
    currentStep,
    currentIndex,
    activeSteps,
    direction,
    isLastStep,
    next,
    back,
    consentSatisfied,
    consentRequirement,
    currentStepPending,
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
  const flowStartedAtRef = useRef(Date.now());
  const stepEnteredAtRef = useRef(Date.now());

  useEffect(() => {
    track(ANALYTICS_EVENTS.ONBOARDING_STARTED);
  }, []);

  // Entry is when the person arrives on the step, which is not always when the
  // view is recorded: a pending gate delays the view but not the reading.
  // biome-ignore lint/correctness/useExhaustiveDependencies: currentStep is the trigger, not a value the body reads
  useEffect(() => {
    stepEnteredAtRef.current = Date.now();
  }, [currentStep]);

  const viewedStepRef = useRef<OnboardingStep | null>(null);
  const recordStepViewed = () => {
    if (currentIndex < 0 || viewedStepRef.current === currentStep) return;
    viewedStepRef.current = currentStep;
    track(ANALYTICS_EVENTS.ONBOARDING_STEP_VIEWED, {
      step_id: currentStep,
      step_index: currentIndex,
      total_steps: activeSteps.length,
    });
  };

  // The ordinary path: the step settles while the person is reading it. This
  // also covers a step entered by the self-heal in useOnboardingFlow, which
  // reaches the person without passing through handleNext.
  // biome-ignore lint/correctness/useExhaustiveDependencies: recordStepViewed reads the same values these deps carry
  useEffect(() => {
    if (currentStepPending) return;
    recordStepViewed();
  }, [currentStep, currentIndex, currentStepPending, activeSteps.length]);

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

  const handleComplete = (context?: StepCompletedContext) => {
    if (isCompleting) return;
    setIsCompleting(true);
    recordStepViewed();
    trackStepCompleted(context);
    track(
      ANALYTICS_EVENTS.ONBOARDING_COMPLETED,
      buildCompletedProps({
        flowStartedAtMs: flowStartedAtRef.current,
        nowMs: Date.now(),
        githubConnected: githubUserIntegrations.length > 0,
      }),
    );
    if (githubUserIntegrations.length > 0) {
      setLastUsedWorkspaceMode("cloud");
    }
    shipIt();
    completeOnboarding();
    openTaskInput();
  };

  const handleNext = (context?: StepCompletedContext) => {
    if (
      currentStep === "consent" &&
      (consentSatisfied !== true || consentSubmitting)
    ) {
      return;
    }
    const safeContext =
      context && "nativeEvent" in context ? undefined : context;
    if (isLastStep) {
      handleComplete(safeContext);
      return;
    }
    recordStepViewed();
    trackStepCompleted(safeContext);
    next();
  };

  const handleBack = () => {
    if (currentStep === "consent" && consentSubmitting) return;
    back();
  };

  const onBack = currentIndex <= 0 ? undefined : handleBack;

  useHotkeys("right", () => handleNext(), { enableOnFormTags: false }, [
    handleNext,
  ]);
  useHotkeys("left", handleBack, { enableOnFormTags: false }, [handleBack]);

  const handleSkip = () => {
    if (isCompleting) return;
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
            <div aria-hidden="true" className="h-20 shrink-0" />
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
            </AnimatePresence>
          </div>
        </div>
      </div>
    </FullScreenLayout>
  );
}
