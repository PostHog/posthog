import {
  ArrowLeft,
  ArrowRight,
  CheckCircle,
  CircleNotch,
  FolderOpen,
  Lightbulb,
} from "@phosphor-icons/react";
import { repoMatchesGitHubRepos } from "@posthog/core/onboarding/repoProvider";
import { cn } from "@posthog/quill";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { Box, Button, Flex, Text } from "@radix-ui/themes";
import { AnimatePresence, motion } from "framer-motion";
import { useMemo } from "react";
import { builderHog } from "../../../assets/hedgehogs";
import { OnboardingHogTip } from "../../../primitives/OnboardingHogTip";
import { FolderPicker } from "../../folder-picker/FolderPicker";
import { GitHubRepoPicker } from "../../folder-picker/GitHubRepoPicker";
import { useUserRepositoryIntegration } from "../../integrations/useIntegrations";
import type { DetectedRepo } from "../types";
import { OptionalBadge } from "./OptionalBadge";
import { PANEL_SHADOW } from "./onboardingStyles";
import { StepActions } from "./StepActions";

interface SelectRepoStepProps {
  onComplete: (skipped: boolean) => void;
  onBack: () => void;
  selectedDirectory: string;
  detectedRepo: DetectedRepo | null;
  isDetectingRepo: boolean;
  onDirectoryChange: (path: string) => void;
}

export function SelectRepoStep({
  onComplete,
  onBack,
  selectedDirectory,
  detectedRepo,
  isDetectingRepo,
  onDirectoryChange,
}: SelectRepoStepProps) {
  const { localWorkspaces } = useHostCapabilities();
  const {
    repositories,
    isLoadingRepos,
    isRefreshingRepos,
    refreshRepositories,
  } = useUserRepositoryIntegration();

  const repoMatchesGitHub = useMemo(
    () => repoMatchesGitHubRepos(detectedRepo, repositories),
    [detectedRepo, repositories],
  );

  return (
    <Flex align="center" height="100%" px="8">
      <Flex
        direction="column"
        align="center"
        className="h-full w-full pt-[24px] pb-[40px]"
      >
        <Flex direction="column" className="min-h-0 flex-1 overflow-y-auto">
          <Flex
            direction="column"
            gap="5"
            className="m-auto w-full max-w-[560px]"
          >
            <Flex direction="column" gap="5" className="w-full">
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                <Flex direction="column" gap="2">
                  <Flex align="center" gap="2">
                    <Text className="font-bold text-(--gray-12) text-2xl">
                      Pick a repo to get started
                    </Text>
                    <OptionalBadge />
                  </Flex>
                  <Text className="text-(--gray-11) text-sm">
                    We'll scan it and suggest some first things to work on. You
                    can also skip this and start from a blank task.
                  </Text>
                </Flex>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.05 }}
              >
                <Box
                  p="5"
                  style={{ boxShadow: PANEL_SHADOW }}
                  className="rounded-[12px] border border-(--gray-a3) bg-(--color-panel-solid)"
                >
                  <Flex direction="column" gap="4">
                    <Flex direction="column" gap="1">
                      <Flex align="center" gap="2">
                        <FolderOpen size={18} className="text-(--gray-12)" />
                        <Text className="font-bold text-(--gray-12) text-base">
                          Choose your repository
                        </Text>
                      </Flex>
                      <Text className="text-(--gray-11) text-sm">
                        {localWorkspaces
                          ? "Select a single repository folder, not a parent folder that contains multiple repos."
                          : "Pick a repository from your connected GitHub organizations."}
                      </Text>
                    </Flex>
                    {localWorkspaces ? (
                      <FolderPicker
                        variant="field"
                        value={selectedDirectory}
                        onChange={onDirectoryChange}
                        placeholder="Select repository..."
                      />
                    ) : (
                      <GitHubRepoPicker
                        value={selectedDirectory || null}
                        onChange={(repo) => onDirectoryChange(repo ?? "")}
                        repositories={repositories}
                        isLoading={isLoadingRepos}
                        onRefresh={refreshRepositories}
                        isRefreshing={isRefreshingRepos}
                        placeholder="Select repository..."
                      />
                    )}
                    <AnimatePresence mode="wait">
                      {localWorkspaces && isDetectingRepo && (
                        <motion.div
                          key="detecting"
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.15 }}
                        >
                          <Flex align="center" gap="2">
                            <CircleNotch
                              size={14}
                              className="animate-spin text-(--gray-9)"
                            />
                            <Text className="text-(--gray-9) text-[13px]">
                              Detecting repository...
                            </Text>
                          </Flex>
                        </motion.div>
                      )}
                      {localWorkspaces &&
                        !isDetectingRepo &&
                        selectedDirectory &&
                        detectedRepo && (
                          <motion.div
                            key="detected"
                            initial={{ opacity: 0, y: 4 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0 }}
                            transition={{ duration: 0.2 }}
                          >
                            <Flex align="center" gap="2">
                              <CheckCircle
                                size={14}
                                weight="fill"
                                className={
                                  repoMatchesGitHub
                                    ? "text-(--green-9)"
                                    : "text-(--gray-9)"
                                }
                              />
                              <Text
                                className={cn(
                                  "text-[13px]",
                                  repoMatchesGitHub
                                    ? "text-(--green-11)"
                                    : "text-(--gray-11)",
                                )}
                              >
                                {repoMatchesGitHub
                                  ? `Linked to ${detectedRepo.fullName} on GitHub`
                                  : `Detected ${detectedRepo.fullName}`}
                              </Text>
                            </Flex>
                          </motion.div>
                        )}
                      {localWorkspaces &&
                        !isDetectingRepo &&
                        selectedDirectory &&
                        !detectedRepo && (
                          <motion.div
                            key="no-repo"
                            initial={{ opacity: 0, y: 4 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0 }}
                            transition={{ duration: 0.2 }}
                          >
                            <Text className="text-(--gray-9) text-[13px]">
                              No git remote detected. You can still continue.
                            </Text>
                          </motion.div>
                        )}
                    </AnimatePresence>
                  </Flex>
                </Box>
              </motion.div>

              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: 0.08 }}
              >
                <Flex align="start" gap="2">
                  <Lightbulb
                    size={16}
                    className="mt-[2px] shrink-0 text-(--gray-10)"
                  />
                  <Text className="text-(--gray-10) text-[13px]">
                    Once you pick a repo we'll look for things like stale
                    feature flags, missing tracking, and other low-effort wins
                    to start from.
                  </Text>
                </Flex>
              </motion.div>
            </Flex>

            <OnboardingHogTip
              hogSrc={builderHog}
              message="No repo? No problem. You can always add one later from the home screen."
              delay={0.15}
            />
          </Flex>
        </Flex>

        <StepActions>
          <Button size="3" variant="outline" color="gray" onClick={onBack}>
            <ArrowLeft size={16} weight="bold" />
            Back
          </Button>
          {selectedDirectory ? (
            <Button size="3" onClick={() => onComplete(false)}>
              Get started
              <ArrowRight size={16} weight="bold" />
            </Button>
          ) : (
            <Button
              size="3"
              variant="outline"
              color="gray"
              onClick={() => onComplete(true)}
            >
              Skip & get started
              <ArrowRight size={16} weight="bold" />
            </Button>
          )}
        </StepActions>
      </Flex>
    </Flex>
  );
}
