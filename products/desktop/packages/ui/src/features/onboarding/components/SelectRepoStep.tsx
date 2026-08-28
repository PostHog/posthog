import {
  ArrowLeft,
  ArrowRight,
  CheckCircle,
  CircleNotch,
} from "@phosphor-icons/react";
import { repoMatchesGitHubRepos } from "@posthog/core/onboarding/repoProvider";
import { cn } from "@posthog/quill";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { Button, Flex, Text } from "@radix-ui/themes";
import { AnimatePresence, motion } from "framer-motion";
import { useMemo, useState } from "react";
import { FolderPicker } from "../../folder-picker/FolderPicker";
import { GitHubRepoPicker } from "../../folder-picker/GitHubRepoPicker";
import { useUserRepositoryIntegration } from "../../integrations/useIntegrations";
import type { DetectedRepo } from "../types";
import { OptionalBadge } from "./OptionalBadge";
import { StepActions } from "./StepActions";

interface SelectRepoStepProps {
  onComplete: (skipped: boolean) => void;
  onBack: () => void;
  selectedDirectory: string;
  detectedRepo: DetectedRepo | null;
  isDetectingRepo: boolean;
  onDirectoryChange: (path: string) => void;
  selectedCloudRepo: string | null;
  onCloudRepoChange: (repo: string | null) => void;
  hasGithubIntegration: boolean | undefined;
}

type RepoSource = "github" | "local";

export function SelectRepoStep({
  onComplete,
  onBack,
  selectedDirectory,
  detectedRepo,
  isDetectingRepo,
  onDirectoryChange,
  selectedCloudRepo,
  onCloudRepoChange,
  hasGithubIntegration,
}: SelectRepoStepProps) {
  const { localWorkspaces } = useHostCapabilities();
  const {
    repositories,
    isLoadingRepos,
    isRefreshingRepos,
    refreshRepositories,
  } = useUserRepositoryIntegration();

  // `null` follows the default source until the user switches explicitly.
  const [chosenSource, setChosenSource] = useState<RepoSource | null>(null);
  const showSourceSwitch = localWorkspaces && hasGithubIntegration === true;
  const repoSource: RepoSource = !localWorkspaces
    ? "github"
    : (chosenSource ?? (hasGithubIntegration ? "github" : "local"));

  const repoMatchesGitHub = useMemo(
    () => repoMatchesGitHubRepos(detectedRepo, repositories),
    [detectedRepo, repositories],
  );

  // Cloud-only hosts keep the picked repo in selectedDirectory.
  const hasSelection =
    localWorkspaces && repoSource === "github"
      ? !!selectedCloudRepo
      : !!selectedDirectory;

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
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <Flex direction="column" gap="2">
                <Flex align="center" gap="2">
                  <Text className="font-bold text-(--gray-12) text-2xl">
                    Pick a repo
                  </Text>
                  <OptionalBadge />
                </Flex>
                <Text className="text-(--gray-11) text-sm">
                  New tasks use this repo by default. You can change it any time
                  from the home screen.
                </Text>
              </Flex>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: 0.05 }}
            >
              <Flex direction="column" gap="2" className="w-full">
                {repoSource === "github" ? (
                  <GitHubRepoPicker
                    value={
                      localWorkspaces
                        ? selectedCloudRepo
                        : selectedDirectory || null
                    }
                    onChange={(repo) =>
                      localWorkspaces
                        ? onCloudRepoChange(repo)
                        : onDirectoryChange(repo ?? "")
                    }
                    repositories={repositories}
                    isLoading={isLoadingRepos}
                    onRefresh={refreshRepositories}
                    isRefreshing={isRefreshingRepos}
                    placeholder="Select repository..."
                    variant="field"
                  />
                ) : (
                  <FolderPicker
                    variant="field"
                    value={selectedDirectory}
                    onChange={onDirectoryChange}
                    placeholder="Select repository..."
                  />
                )}

                <AnimatePresence mode="wait">
                  {repoSource === "local" && isDetectingRepo && (
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
                  {repoSource === "local" &&
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
                  {repoSource === "local" &&
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

                {showSourceSwitch && (
                  <button
                    type="button"
                    onClick={() => {
                      const nextSource =
                        repoSource === "github" ? "local" : "github";
                      // Clear the source being left so a later Skip cannot
                      // silently assign or persist a repo the user
                      // navigated away from.
                      if (nextSource === "local") {
                        onCloudRepoChange(null);
                      } else {
                        onDirectoryChange("");
                      }
                      setChosenSource(nextSource);
                    }}
                    className="cursor-pointer self-start border-0 bg-transparent p-0 text-(--gray-10) text-[13px] underline hover:text-(--gray-11)"
                  >
                    {repoSource === "github"
                      ? "Use a local folder instead"
                      : "Back to GitHub repos"}
                  </button>
                )}
              </Flex>
            </motion.div>
          </Flex>
        </Flex>

        <StepActions>
          <Button size="3" variant="outline" color="gray" onClick={onBack}>
            <ArrowLeft size={16} weight="bold" />
            Back
          </Button>
          {hasSelection ? (
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
