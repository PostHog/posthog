import { Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import { PlanSectionComment } from "./PlanSectionComment";
import type { PlanReviewComment } from "./planReview";

interface PlanReviewCommentCardProps {
  comment: PlanReviewComment;
  reviewable: boolean;
  canEdit: boolean;
  onUpdate?: (text: string) => void;
  onRemove: () => void;
}

export function PlanReviewCommentCard({
  comment,
  reviewable,
  canEdit,
  onUpdate,
  onRemove,
}: PlanReviewCommentCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const colorClasses = comment.stale
    ? "border-orange-6 bg-orange-2"
    : "border-gray-6 bg-gray-2";

  if (isEditing) {
    return (
      <div className={`mt-2 rounded-md border px-2.5 py-2 ${colorClasses}`}>
        <PlanSectionComment
          initialText={comment.text}
          onDismiss={() => setIsEditing(false)}
          onSubmit={(text) => {
            if (onUpdate) {
              onUpdate(text);
            }
            setIsEditing(false);
          }}
        />
      </div>
    );
  }

  return (
    <div
      className={`mt-2 rounded-md border px-2.5 py-2 text-[13px] ${colorClasses}`}
    >
      {comment.stale && (
        <Text as="div" size="1" color="orange" className="mb-1">
          This comment refers to an earlier version of the plan.
        </Text>
      )}
      <Text as="div" className="whitespace-pre-wrap text-gray-12">
        {comment.text}
      </Text>
      {reviewable && (
        <Flex gap="2" className="mt-1">
          {canEdit && (
            <button
              type="button"
              className="text-[11px] text-gray-10 hover:text-gray-12"
              onClick={() => setIsEditing(true)}
            >
              Edit
            </button>
          )}
          <button
            type="button"
            className="text-[11px] text-gray-10 hover:text-gray-12"
            onClick={onRemove}
          >
            Remove
          </button>
        </Flex>
      )}
    </div>
  );
}
