import {
  ArrowsClockwise,
  CloudArrowUp,
  GitBranch,
  GitPullRequest,
} from "@phosphor-icons/react";
import type { GitActionType } from "@posthog/ui/features/sessions/components/gitActionMarker";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

function getActionIcon(actionType: GitActionType): ReactNode {
  switch (actionType) {
    case "commit-push":
      return <CloudArrowUp size={14} weight="bold" />;
    case "publish":
      return <GitBranch size={14} weight="bold" />;
    case "push":
      return <CloudArrowUp size={14} weight="bold" />;
    case "pull":
      return <ArrowsClockwise size={14} weight="bold" />;
    case "sync":
      return <ArrowsClockwise size={14} weight="bold" />;
    case "create-pr":
      return <GitPullRequest size={14} weight="bold" />;
    default:
      return <CloudArrowUp size={14} weight="bold" />;
  }
}

function getActionLabel(actionType: GitActionType): string {
  switch (actionType) {
    case "commit-push":
      return "Commit & Push";
    case "publish":
      return "Publish Branch";
    case "push":
      return "Push";
    case "pull":
      return "Pull";
    case "sync":
      return "Sync";
    case "create-pr":
      return "Create PR";
    default:
      return "Git Action";
  }
}

interface GitActionMessageProps {
  actionType: GitActionType;
}

export function GitActionMessage({ actionType }: GitActionMessageProps) {
  return (
    <Box className="mt-4 max-w-[95%] xl:max-w-[60%]">
      <Flex
        align="center"
        gap="2"
        className="rounded-lg border border-accent-6 bg-accent-3 px-3 py-2"
      >
        <Flex
          align="center"
          justify="center"
          className="rounded bg-accent-9 p-1"
          style={{ color: "white" }}
        >
          {getActionIcon(actionType)}
        </Flex>
        <Text className="font-medium text-sm">
          {getActionLabel(actionType)}
        </Text>
        <Badge size="1" color="gray" variant="soft">
          Git Action
        </Badge>
      </Flex>
    </Box>
  );
}
