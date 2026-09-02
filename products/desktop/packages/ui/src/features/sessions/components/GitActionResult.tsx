import {
  ArrowSquareOut,
  CheckCircle,
  GitCommit,
  GitPullRequest,
} from "@phosphor-icons/react";
import { useHostTRPC } from "@posthog/host-router/react";
import type { GitActionType } from "@posthog/ui/features/sessions/components/GitActionMessage";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { Badge, Box, Button, Flex, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";

interface GitActionResultProps {
  actionType: GitActionType;
  repoPath: string;
  turnId: string;
}

export function GitActionResult({
  actionType,
  repoPath,
  turnId: _turnId,
}: GitActionResultProps) {
  const trpc = useHostTRPC();

  const { data: commitInfo } = useQuery(
    trpc.git.getLatestCommit.queryOptions(
      { directoryPath: repoPath },
      {
        enabled: !!repoPath,
        staleTime: 0,
      },
    ),
  );

  const { data: repoInfo } = useQuery(
    trpc.git.getGitRepoInfo.queryOptions(
      { directoryPath: repoPath },
      {
        enabled: !!repoPath,
        staleTime: 30000,
      },
    ),
  );

  const handleOpenUrl = (url: string) => {
    openExternalUrl(url);
  };

  const showCommit = commitInfo != null;
  const showPrLink = repoInfo?.compareUrl != null;

  if (!showCommit && !showPrLink) {
    return null;
  }

  return (
    <Box className="mt-3 rounded-lg border border-green-6 bg-green-2 p-3">
      <Flex direction="column" gap="2">
        <Flex align="center" gap="2">
          <CheckCircle size={16} weight="fill" className="text-green-9" />
          <Text className="font-medium text-green-11 text-sm">
            {getCompletionLabel(actionType)}
          </Text>
        </Flex>

        {showCommit && commitInfo && (
          <Flex align="center" gap="2" className="mt-1">
            <GitCommit size={14} className="text-gray-10" />
            <Text className="font-mono text-[13px] text-gray-11">
              {commitInfo.shortSha}
            </Text>
            <Text
              className="max-w-[200px] overflow-hidden whitespace-nowrap text-[13px] text-gray-11"
              style={{
                textOverflow: "ellipsis",
              }}
            >
              {commitInfo.message}
            </Text>
            <Badge size="1" color="green" variant="soft">
              Latest
            </Badge>
          </Flex>
        )}

        {showPrLink && repoInfo?.compareUrl && (
          <Flex align="center" gap="2" className="mt-1">
            <GitPullRequest size={14} className="text-purple-9" />
            <Text className="font-medium text-[13px]">
              {repoInfo.currentBranch}
            </Text>
            <Button
              size="1"
              variant="ghost"
              onClick={() => handleOpenUrl(repoInfo.compareUrl as string)}
            >
              <ArrowSquareOut size={12} />
              Open on GitHub
            </Button>
          </Flex>
        )}
      </Flex>
    </Box>
  );
}

function getCompletionLabel(actionType: GitActionType): string {
  switch (actionType) {
    case "commit-push":
      return "Changes Committed & Pushed";
    case "push":
      return "Changes Pushed";
    case "pull":
      return "Changes Pulled";
    case "sync":
      return "Repository Synced";
    case "publish":
      return "Branch Published";
    case "create-pr":
      return "Ready for Pull Request";
    default:
      return "Git Action Completed";
  }
}
