import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import { isAnyIntegrationStale } from "@posthog/core/onboarding/githubConnectPanel";
import { Button, Heading, Text } from "@posthog/quill";
import type { OnboardingStepCompletedProperties } from "@posthog/shared/analytics-events";
import { GithubConnectionEmpty } from "@posthog/ui/features/integrations/components/GithubConnectionEmpty";
import {
  useUserGithubIntegrations,
  useUserRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { OptionalBadge } from "@posthog/ui/features/onboarding/components/OptionalBadge";
import { StepActions } from "@posthog/ui/features/onboarding/components/StepActions";
import { motion, useReducedMotion } from "framer-motion";
import { GitHubConnectPanel } from "./GitHubConnectPanel";

type StepContext = Pick<OnboardingStepCompletedProperties, "github_connected">;

interface ConnectGitHubStepProps {
  onNext: (context?: StepContext) => void;
  onBack?: () => void;
}

export function ConnectGitHubStep({ onNext, onBack }: ConnectGitHubStepProps) {
  const shouldReduceMotion = useReducedMotion() === true;
  const { data: githubUserIntegrations = [] } = useUserGithubIntegrations();
  const { failedInstallationIds } = useUserRepositoryIntegration();
  // A revoked installation still leaves its row behind, so the link must not
  // read as healthy while the card below says it needs reconnecting.
  const isConnected =
    githubUserIntegrations.length > 0 &&
    !isAnyIntegrationStale(githubUserIntegrations, failedInstallationIds);
  const handleContinue = () => {
    onNext({ github_connected: isConnected });
  };

  return (
    <main className="w-full">
      <div className="mx-auto flex w-full max-w-[480px] flex-col gap-4">
        <motion.div
          initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: "easeOut" }}
          className="flex flex-col gap-1.5"
        >
          <div className="flex items-center gap-2">
            {/* biome-ignore lint/a11y/useHeadingContent: Quill supplies the heading text through this render target. */}
            <Heading size="xl" render={<h1 className="font-bold" />}>
              Connect your codebase
            </Heading>
            <OptionalBadge />
          </div>
          <Text size="sm" variant="muted">
            Unlocks cloud environments and self-driving tasks.
          </Text>
        </motion.div>

        <motion.div
          key="github-panel"
          initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, delay: 0.03, ease: "easeOut" }}
        >
          <div className="flex flex-col gap-4">
            <GithubConnectionEmpty
              connected={isConnected}
              showLearnMore={false}
              className="border-solid"
              description={
                isConnected
                  ? "GitHub connected"
                  : "Gives PostHog Desktop read access to your repos"
              }
            >
              <GitHubConnectPanel />
            </GithubConnectionEmpty>
            <StepActions
              primaryAction={
                <Button
                  size="lg"
                  variant={isConnected ? "primary" : "outline"}
                  onClick={handleContinue}
                >
                  {isConnected ? "Continue" : "Skip for now"}
                  <ArrowRight size={16} weight="bold" />
                </Button>
              }
            >
              {onBack && (
                <Button size="lg" onClick={onBack}>
                  <ArrowLeft size={16} weight="bold" />
                  Back
                </Button>
              )}
            </StepActions>
          </div>
        </motion.div>
      </div>
    </main>
  );
}
