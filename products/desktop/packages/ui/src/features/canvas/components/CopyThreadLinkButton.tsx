import { CopyIcon, DotsThreeIcon, LinkIcon } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { copyChannelLink } from "@posthog/ui/features/canvas/utils/copyChannelLink";
import { toast } from "@posthog/ui/primitives/toast";

export function CopyThreadLinkButton({
  branchName,
  channelId,
  taskId,
}: {
  branchName?: string;
  channelId: string;
  taskId: string;
}) {
  const copyBranchName = async (): Promise<void> => {
    if (!branchName) {
      return;
    }

    try {
      await navigator.clipboard.writeText(branchName);
      toast.success("Branch name copied");
    } catch {
      toast.error("Couldn't copy branch name");
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            size="icon-sm"
            aria-label="Thread actions"
            className="no-drag"
            data-attr="thread-actions-menu"
          />
        }
      >
        <DotsThreeIcon size={14} weight="bold" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-auto">
        <DropdownMenuItem
          data-attr="copy-thread-link"
          onClick={() => void copyChannelLink(channelId, "title_bar", taskId)}
        >
          <LinkIcon size={13} />
          Copy link to thread
        </DropdownMenuItem>
        {branchName ? (
          <DropdownMenuItem
            data-attr="copy-thread-branch-name"
            onClick={() => void copyBranchName()}
          >
            <CopyIcon size={13} />
            Copy branch name
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
