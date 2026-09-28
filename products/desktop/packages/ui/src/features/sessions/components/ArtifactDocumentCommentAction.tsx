import { ChatCircleIcon } from "@phosphor-icons/react";
import type { CommentTarget } from "@posthog/core/comments/anchors";
import {
  Button,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { useState } from "react";
import { commentAgentContext } from "../commentAgentContext";
import { sendCommentToAgent } from "../sendCommentToAgent";
import { CommentComposer } from "./CommentComposer";
import { useCreateComment } from "./useComments";

export function ArtifactDocumentCommentAction({
  target,
  taskId,
  name,
  onCreated,
}: {
  target: CommentTarget;
  taskId: string;
  name: string;
  onCreated?: (commentId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const { members } = useOrgMembers();
  const createComment = useCreateComment(target, taskId);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger
          render={
            <PopoverTrigger
              render={
                <Button size="icon" variant="default" aria-label="Comment…">
                  <ChatCircleIcon size={14} />
                </Button>
              }
            />
          }
        />
        <TooltipContent>Comment on this artifact</TooltipContent>
      </Tooltip>
      <PopoverContent align="end" sideOffset={6} className="w-96 p-2">
        <CommentComposer
          value={draft}
          onValueChange={setDraft}
          onSubmit={async (content, mentions) => {
            const comment = await createComment.mutateAsync({
              content,
              context: { anchor: { kind: "document" } },
              mentions,
            });
            onCreated?.(comment.id);
            setDraft("");
            setOpen(false);
          }}
          onCancel={() => setOpen(false)}
          members={members}
          placeholder="Comment on this artifact… Type @ to mention someone"
          rows={2}
          disabled={createComment.isPending}
          autoFocus
          onSendToAgent={(content) =>
            sendCommentToAgent({
              taskId,
              comment: content,
              context: commentAgentContext(
                { kind: "document" },
                { kind: "artifact", name },
              ),
              surface: "artifact",
            })
          }
        />
      </PopoverContent>
    </Popover>
  );
}
