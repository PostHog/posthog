import {
  ArrowLeft,
  ArrowRight,
  CheckCircle,
  FolderOpen,
} from "@phosphor-icons/react";
import { repoMatchesGitHubRepos } from "@posthog/core/onboarding/repoProvider";
import {
  Button,
  cn,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Heading,
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
  Text,
} from "@posthog/quill";
import { FolderPicker } from "@posthog/ui/features/folder-picker/FolderPicker";
import { GitHubRepoPicker } from "@posthog/ui/features/folder-picker/GitHubRepoPicker";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { useUserRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { getFilePath } from "@posthog/ui/utils/getFilePath";
import { motion, useReducedMotion } from "framer-motion";
import { type DragEvent, useMemo, useRef, useState } from "react";
import type { DetectedRepo } from "../types";
import { OptionalBadge } from "./OptionalBadge";
import { StepActions } from "./StepActions";

function handleDragOver(event: DragEvent<HTMLDivElement>): void {
  if (!event.dataTransfer.types.includes("Files")) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
}

interface SelectRepoStepProps {
  onComplete: (skipped: boolean) => void | Promise<void>;
  onBack: () => void;
  selectedDirectory: string;
  detectedRepo: DetectedRepo | null;
  isDetectingRepo: boolean;
  onDirectoryChange: (path: string) => void;
  selectedCloudRepo: string | null;
  onCloudRepoChange: (repo: string | null) => void;
  hasGithubIntegration: boolean | undefined;
  isCompleting: boolean;
}

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
  isCompleting,
}: SelectRepoStepProps) {
  const shouldReduceMotion = useReducedMotion() === true;
  const { localWorkspaces } = useHostCapabilities();
  const { addFolder } = useFolders();
  const {
    repositories,
    isLoadingRepos,
    isRefreshingRepos,
    refreshRepositories,
  } = useUserRepositoryIntegration();
  const [isDraggingFolder, setIsDraggingFolder] = useState(false);
  const [dropError, setDropError] = useState<string | null>(null);
  const dragDepthRef = useRef(0);

  const useGithubRepository = !localWorkspaces || hasGithubIntegration === true;
  const hasSelection = useGithubRepository
    ? localWorkspaces
      ? selectedCloudRepo !== null
      : selectedDirectory !== ""
    : selectedDirectory !== "";
  const repoMatchesGitHub = useMemo(
    () => repoMatchesGitHubRepos(detectedRepo, repositories),
    [detectedRepo, repositories],
  );

  const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    dragDepthRef.current += 1;
    setIsDraggingFolder(true);
  };

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) setIsDraggingFolder(false);
  };

  const handleFolderDrop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    dragDepthRef.current = 0;
    setIsDraggingFolder(false);
    setDropError(null);

    const item = event.dataTransfer.items[0];
    const entry = item?.webkitGetAsEntry?.();
    if (entry && !entry.isDirectory) {
      setDropError("Drop a folder, not a file.");
      return;
    }

    const file = event.dataTransfer.files[0];
    const path = file ? getFilePath(file) : "";
    if (!path) {
      setDropError(
        "This folder path is not available. Choose the folder instead.",
      );
      return;
    }

    try {
      await addFolder(path);
      onDirectoryChange(path);
    } catch {
      setDropError(
        "PostHog could not add this folder. Choose the folder instead.",
      );
    }
  };

  const localFolderStatus = selectedDirectory ? (
    <Item
      variant="muted"
      size="sm"
      tone={
        isDetectingRepo
          ? "default"
          : detectedRepo && repoMatchesGitHub
            ? "success"
            : "info"
      }
      aria-live="polite"
    >
      <ItemMedia variant="icon">
        {isDetectingRepo ? (
          <Spinner />
        ) : detectedRepo ? (
          <CheckCircle size={15} weight="fill" />
        ) : (
          <FolderOpen size={15} weight="fill" />
        )}
      </ItemMedia>
      <ItemContent>
        <ItemTitle>
          {isDetectingRepo
            ? "Checking folder"
            : detectedRepo
              ? repoMatchesGitHub
                ? `Linked to ${detectedRepo.fullName} on GitHub`
                : `Detected ${detectedRepo.fullName}`
              : "Folder ready"}
        </ItemTitle>
        {!isDetectingRepo && !detectedRepo && (
          <ItemDescription>
            No Git remote was detected. You can still use this folder.
          </ItemDescription>
        )}
      </ItemContent>
    </Item>
  ) : null;

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
              Pick a repo
            </Heading>
            <OptionalBadge />
          </div>
          <Text size="sm" variant="muted">
            New tasks use this repo by default. Change it anytime from home.
          </Text>
        </motion.div>

        <motion.div
          initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, delay: 0.03, ease: "easeOut" }}
          className="flex flex-col gap-4"
        >
          {useGithubRepository ? (
            <GitHubRepoPicker
              value={
                localWorkspaces ? selectedCloudRepo : selectedDirectory || null
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
              placeholder="Select repository…"
              variant="field"
              disabled={isCompleting}
            />
          ) : (
            <Empty
              className={cn("py-6", isDraggingFolder && "bg-muted")}
              aria-live="polite"
              onDragEnter={handleDragEnter}
              onDragLeave={handleDragLeave}
              onDragOver={handleDragOver}
              onDrop={(event) => void handleFolderDrop(event)}
            >
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <FolderOpen size={18} weight="fill" />
                </EmptyMedia>
                <EmptyTitle>
                  {isDraggingFolder
                    ? "Drop your folder"
                    : "Choose a local folder"}
                </EmptyTitle>
                <EmptyDescription>
                  Drop a folder here, or choose one from your computer.
                </EmptyDescription>
              </EmptyHeader>
              <EmptyContent className="w-full max-w-none">
                <FolderPicker
                  value={selectedDirectory}
                  onChange={(path) => {
                    setDropError(null);
                    onDirectoryChange(path);
                  }}
                  placeholder="Choose folder…"
                />
                {dropError && (
                  <Text size="xs" variant="destructive">
                    {dropError}
                  </Text>
                )}
                {localFolderStatus}
              </EmptyContent>
            </Empty>
          )}

          <StepActions
            primaryAction={
              <Button
                size="lg"
                variant={hasSelection ? "primary" : "outline"}
                loading={isCompleting}
                onClick={() => void onComplete(!hasSelection)}
              >
                {hasSelection ? "Get started" : "Skip & get started"}
                <ArrowRight size={16} weight="bold" />
              </Button>
            }
          >
            <Button size="lg" disabled={isCompleting} onClick={onBack}>
              <ArrowLeft size={16} weight="bold" />
              Back
            </Button>
          </StepActions>
        </motion.div>
      </div>
    </main>
  );
}
