import { PencilSimple, Trash } from "@phosphor-icons/react";
import { useReviewDraftsStore } from "@posthog/ui/features/code-review/reviewDraftsStore";
import { Badge, Flex, IconButton, Text } from "@radix-ui/themes";

interface DraftCommentAnnotationProps {
  taskId: string;
  draftId: string;
  onEdit: (draftId: string) => void;
}

export function DraftCommentAnnotation({
  taskId,
  draftId,
  onEdit,
}: DraftCommentAnnotationProps) {
  const draft = useReviewDraftsStore((s) =>
    (s.drafts[taskId] ?? []).find((d) => d.id === draftId),
  );
  const removeDraft = useReviewDraftsStore((s) => s.removeDraft);

  if (!draft) return null;

  return (
    <div className="px-3 py-1.5">
      <div
        data-draft-comment-annotation=""
        className="whitespace-normal rounded-md border border-(--gray-6) border-dashed bg-(--gray-2) px-2.5 py-2 font-sans"
      >
        <Flex align="center" justify="between" gap="2" className="mb-1">
          <Badge color="gray" size="1" variant="soft">
            Pending review comment
          </Badge>
          <Flex gap="1">
            <IconButton
              size="1"
              variant="ghost"
              color="gray"
              onClick={() => onEdit(draftId)}
              aria-label="Edit draft comment"
            >
              <PencilSimple size={12} />
            </IconButton>
            <IconButton
              size="1"
              variant="ghost"
              color="gray"
              onClick={() => removeDraft(taskId, draftId)}
              aria-label="Delete draft comment"
            >
              <Trash size={12} />
            </IconButton>
          </Flex>
        </Flex>
        <Text
          as="div"
          size="1"
          className="whitespace-pre-wrap text-(--gray-12) leading-normal"
        >
          {draft.text}
        </Text>
      </div>
    </div>
  );
}
