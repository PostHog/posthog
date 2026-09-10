import { PaperPlaneTilt } from "@phosphor-icons/react";
import { buildBatchedInlineCommentsPrompt } from "@posthog/core/code-review/reviewPrompts";
import { Button } from "@posthog/quill";
import { Badge, Flex } from "@radix-ui/themes";
import { sendPromptToAgent } from "../../sessions/sendPromptToAgent";
import { useReviewDraftsStore } from "../reviewDraftsStore";

interface PendingReviewBarProps {
  taskId: string;
}

export function PendingReviewBar({ taskId }: PendingReviewBarProps) {
  const drafts = useReviewDraftsStore((s) => s.drafts[taskId] ?? []);
  const clearDrafts = useReviewDraftsStore((s) => s.clearDrafts);

  if (drafts.length === 0) return null;

  const handleSend = () => {
    const prompt = buildBatchedInlineCommentsPrompt(drafts);
    if (!prompt) return;
    sendPromptToAgent(taskId, prompt);
    clearDrafts(taskId);
  };

  return (
    <div className="shrink-0 border-(--gray-5) border-t bg-(--gray-2)">
      <Flex align="center" justify="between" gap="3" className="px-3 py-2">
        <Badge color="iris" variant="soft" size="1">
          Pending review · {drafts.length}
        </Badge>
        <Flex align="center" gap="2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => clearDrafts(taskId)}
          >
            Discard all
          </Button>
          <Button size="sm" variant="primary" onClick={handleSend}>
            <PaperPlaneTilt size={12} weight="fill" />
            Send to agent
          </Button>
        </Flex>
      </Flex>
    </div>
  );
}
