import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import { isAnyIntegrationStale } from "@posthog/core/onboarding/githubConnectPanel";
import { Button, Card, CardContent, Heading, Text } from "@posthog/quill";
import type { OnboardingStepCompletedProperties } from "@posthog/shared/analytics-events";
import {
  useUserGithubIntegrations,
  useUserRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { GithubConnectionLink } from "@posthog/ui/features/onboarding/components/GithubConnectionLink";
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
        >
          <GithubConnectionLink connected={isConnected} />
        </motion.div>

        <motion.div
          initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, delay: 0.03, ease: "easeOut" }}
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
            Code access helps us understand your product and helps you build.
          </Text>
        </motion.div>

        <motion.div
          key="github-panel"
          initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, delay: 0.06, ease: "easeOut" }}
        >
          <Card className="w-full">
            <CardContent className="flex flex-col gap-4">
              <GitHubConnectPanel />
              <StepActions
                primaryAction={
                  <Button size="lg" variant="primary" onClick={handleContinue}>
                    {isConnected ? "Continue" : "Skip for now"}
                    <ArrowRight size={16} weight="bold" />
                  </Button>
                }
              >
                {onBack && (
                  <Button size="lg" variant="outline" onClick={onBack}>
                    <ArrowLeft size={16} weight="bold" />
                    Back
                  </Button>
                )}
              </StepActions>
            </CardContent>
          </Card>
        </motion.div>
      </div>
    </main>
  );
}
