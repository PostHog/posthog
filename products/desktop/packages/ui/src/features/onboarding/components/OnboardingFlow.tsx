import { ArrowRight, SignOut } from "@phosphor-icons/react";
import {
  buildAbandonedProps,
  buildCompletedProps,
  buildStepCompletedProps,
  type StepCompletedContext,
} from "@posthog/core/onboarding/analytics";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useLogoutMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { useUserGithubIntegrations } from "@posthog/ui/features/integrations/useIntegrations";
import { ConnectGitHubStep } from "@posthog/ui/features/onboarding/components/ConnectGitHubStep";
import { ImportConfigStep } from "@posthog/ui/features/onboarding/components/ImportConfigStep";
import { InstallCliStep } from "@posthog/ui/features/onboarding/components/InstallCliStep";
import { StepIndicator } from "@posthog/ui/features/onboarding/components/StepIndicator";
import { WelcomeScreen } from "@posthog/ui/features/onboarding/components/WelcomeScreen";
import { useOnboardingFlow } from "@posthog/ui/features/onboarding/hooks/useOnboardingFlow";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { shipIt } from "@posthog/ui/primitives/confetti";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import { Button, Flex } from "@radix-ui/themes";
import { AnimatePresence, LayoutGroup, motion } from "framer-motion";
import { useEffect, useRef } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import { InviteCodeStep } from "./InviteCodeStep";
import { ProjectSelectStep } from "./ProjectSelectStep";
import { SelectRepoStep } from "./SelectRepoStep";

const IS_DEV = import.meta.env.DEV;

const stepVariants = {
  enter: (dir: number) => ({ opacity: 0, x: dir * 20 }),
  center: { opacity: 1, x: 0 },
  exit: (dir: number) => ({ opacity: 0, x: dir * -20 }),
};

export function OnboardingFlow() {
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
    trackStepCompleted(context);
    trackStepViewed(currentIndex + 1);
    next();
  };

  const handleBack = () => {
    trackStepViewed(currentIndex - 1);
    back();
  };

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

  const footerRight = (
    <Flex gap="5">
      {isAuthenticated && (
        <Button
          size="1"
          variant="ghost"
          color="gray"
          onClick={handleLogout}
          className="opacity-50"
        >
          <SignOut size={14} />
          Log out
        </Button>
      )}
      {IS_DEV && (
        <Button
          size="1"
          variant="ghost"
          color="gray"
          onClick={handleSkip}
          className="opacity-50"
        >
          <ArrowRight size={14} weight="bold" />
          Skip setup
        </Button>
      )}
    </Flex>
  );

  return (
    <FullScreenLayout footerRight={footerRight}>
      <LayoutGroup>
        <AnimatePresence mode="wait" custom={direction}>
          {currentStep === "welcome" && (
            <motion.div
              key="welcome"
              custom={direction}
              initial="enter"
              animate="center"
              exit="exit"
              variants={stepVariants}
              transition={{ duration: 0.3 }}
              className="min-h-0 w-full flex-1"
            >
              <WelcomeScreen onNext={handleNext} />
            </motion.div>
          )}

          {currentStep === "project-select" && (
            <motion.div
              key="project-select"
              custom={direction}
              initial="enter"
              animate="center"
              exit="exit"
              variants={stepVariants}
              transition={{ duration: 0.3 }}
              className="min-h-0 w-full flex-1"
            >
              <ProjectSelectStep onNext={handleNext} onBack={handleBack} />
            </motion.div>
          )}

          {currentStep === "invite-code" && (
            <motion.div
              key="invite-code"
              custom={direction}
              initial="enter"
              animate="center"
              exit="exit"
              variants={stepVariants}
              transition={{ duration: 0.3 }}
              className="min-h-0 w-full flex-1"
            >
              <InviteCodeStep onNext={handleNext} onBack={handleBack} />
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
              className="min-h-0 w-full flex-1"
            >
              <ConnectGitHubStep onNext={handleNext} onBack={handleBack} />
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
              className="min-h-0 w-full flex-1"
            >
              <InstallCliStep onNext={handleNext} onBack={handleBack} />
            </motion.div>
          )}

          {currentStep === "import-config" && (
            <motion.div
              key="import-config"
              custom={direction}
              initial="enter"
              animate="center"
              exit="exit"
              variants={stepVariants}
              transition={{ duration: 0.3 }}
              className="min-h-0 w-full flex-1"
            >
              <ImportConfigStep onNext={handleNext} onBack={handleBack} />
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
              className="min-h-0 w-full flex-1"
            >
              <SelectRepoStep
                onComplete={handleComplete}
                onBack={handleBack}
                selectedDirectory={selectedDirectory}
                detectedRepo={detectedRepo}
                isDetectingRepo={isDetectingRepo}
                onDirectoryChange={handleDirectoryChange}
              />
            </motion.div>
          )}
        </AnimatePresence>

        <StepIndicator currentStep={currentStep} activeSteps={activeSteps} />
      </LayoutGroup>
    </FullScreenLayout>
  );
}
