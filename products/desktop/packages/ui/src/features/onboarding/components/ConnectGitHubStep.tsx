import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import { isAnyIntegrationStale } from "@posthog/core/onboarding/githubConnectPanel";
import type { OnboardingStepCompletedProperties } from "@posthog/shared/analytics-events";
import {
  useUserGithubIntegrations,
  useUserRepositoryIntegration,
} from "@posthog/ui/features/integrations/useIntegrations";
import { GithubConnectionLink } from "@posthog/ui/features/onboarding/components/GithubConnectionLink";
import { OptionalBadge } from "@posthog/ui/features/onboarding/components/OptionalBadge";
import { StepActions } from "@posthog/ui/features/onboarding/components/StepActions";
import { Button, Flex, Text } from "@radix-ui/themes";
import { motion } from "framer-motion";
import { GitHubConnectPanel } from "./GitHubConnectPanel";

type StepContext = Pick<OnboardingStepCompletedProperties, "github_connected">;

interface ConnectGitHubStepProps {
  onNext: (context?: StepContext) => void;
  onBack?: () => void;
}

export function ConnectGitHubStep({ onNext, onBack }: ConnectGitHubStepProps) {
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
    <Flex align="center" justify="center" height="100%" px="8">
      <Flex
        direction="column"
        align="center"
        className="h-full w-full max-w-[480px] pt-[24px] pb-[40px]"
      >
        <Flex
          direction="column"
          align="center"
          className="min-h-0 w-full flex-1 overflow-y-auto"
        >
          <Flex
            direction="column"
            gap="5"
            style={{ margin: "auto 0" }}
            className="w-full"
          >
            <Flex direction="column" gap="4" className="w-full">
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                <GithubConnectionLink connected={isConnected} />
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.02 }}
              >
                <Flex direction="column" gap="2">
                  <Flex align="center" gap="2">
                    <Text className="font-bold text-(--gray-12) text-2xl">
                      Connect GitHub
                    </Text>
                    <OptionalBadge />
                  </Flex>
                  <Text className="text-(--gray-11) text-sm">
                    Allows agents to run tasks in the cloud, push branches, and
                    open pull requests.
                  </Text>
                </Flex>
              </motion.div>

              <motion.div
                key="github-panel"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.05 }}
              >
                <GitHubConnectPanel />
              </motion.div>
            </Flex>
          </Flex>
        </Flex>

        <StepActions>
          {onBack && (
            <Button size="3" variant="outline" color="gray" onClick={onBack}>
              <ArrowLeft size={16} weight="bold" />
              Back
            </Button>
          )}
          <Button
            size="3"
            variant={isConnected ? "solid" : "outline"}
            color={isConnected ? undefined : "gray"}
            onClick={handleContinue}
          >
            {isConnected ? "Continue" : "Skip for now"}
            <ArrowRight size={16} weight="bold" />
          </Button>
        </StepActions>
      </Flex>
    </Flex>
  );
}
