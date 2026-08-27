import { ChatCircleIcon } from "@phosphor-icons/react";
import { PI_SESSION_CONTROLLER } from "@posthog/core/pi-runtime/identifiers";
import type { PiSessionController } from "@posthog/core/pi-runtime/piSessionController";
import { useService } from "@posthog/di/react";
import { Button, Textarea } from "@posthog/quill";
import {
  type AgentFlowReview,
  buildAgentFlowRespondCommand,
} from "@posthog/shared";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { useCommentsQuery } from "@posthog/ui/features/sessions/components/useComments";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import { useState } from "react";
import { FlowHandoffCard } from "./FlowHandoffCard";
import { FlowReviewOutcome } from "./FlowReviewOutcome";
import { readFlowReview, toReviewComments } from "./handoffReview";
import {
  readFlowHandoff,
  useFlowHandoffArtifact,
} from "./useFlowHandoffArtifact";

function approvalIdFromCardId(cardId: string): string | undefined {
  const marker = ":approval:";
  const index = cardId.indexOf(marker);
  return index === -1 ? undefined : cardId.slice(index + marker.length);
}

function cardText(toolCall: ToolViewProps["toolCall"]): string {
  return (toolCall.content ?? [])
    .flatMap((block) =>
      block.type === "content" && block.content.type === "text"
        ? [block.content.text]
        : [],
    )
    .join("\n");
}

export function FlowApprovalView({ toolCall }: ToolViewProps) {
  const controller = useService<PiSessionController>(PI_SESSION_CONTROLLER);
  const taskId = useSessionTaskId();
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const approvalId = approvalIdFromCardId(toolCall.toolCallId);
  const text = cardText(toolCall);
  const handoff = readFlowHandoff(toolCall.rawInput);
  const resolvedApproved = toolCall.status === "completed";
  const resolvedRejected = toolCall.status === "failed";
  const pending = !resolvedApproved && !resolvedRejected;

  const artifact = useFlowHandoffArtifact(pending ? taskId : null, handoff);
  const artifactId = artifact.data?.artifactId ?? null;
  const commentTarget = artifactId
    ? ({ scope: "task_artifact", itemId: artifactId } as const)
    : null;
  const comments = useCommentsQuery(commentTarget, taskId ?? "", {
    enabled: pending && !!taskId && !!commentTarget,
  });
  const openComments = toReviewComments(comments.data ?? []);

  const respond = (outcome: "approve" | "reject", note?: string) => {
    if (!taskId || !approvalId || submitting) {
      return;
    }
    setSubmitting(true);
    const review: AgentFlowReview = {
      comments: openComments,
      ...(note?.trim() ? { note: note.trim() } : {}),
    };
    void controller
      .submit(
        taskId,
        buildAgentFlowRespondCommand(approvalId, outcome, review),
        false,
        "steer",
      )
      .catch(() => {
        setSubmitting(false);
      });
  };

  if (!pending) {
    return (
      <FlowReviewOutcome
        approved={resolvedApproved}
        review={readFlowReview(toolCall.rawOutput)}
        fallbackText={text}
      />
    );
  }

  const commentCount = openComments.length;

  return (
    <div className="my-3 flex max-w-3xl flex-col gap-2">
      <FlowHandoffCard handoff={handoff} fallbackText={text} />
      {showFeedback ? (
        <>
          <Textarea
            value={feedback}
            onChange={(event) => setFeedback(event.currentTarget.value)}
            rows={3}
            placeholder="What should change?"
            aria-label="Feedback for the revision"
            disabled={submitting}
          />
          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={submitting}
              onClick={() => setShowFeedback(false)}
            >
              Back
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              loading={submitting}
              disabled={submitting || (!feedback.trim() && commentCount === 0)}
              onClick={() => respond("reject", feedback)}
            >
              Send for revision
            </Button>
          </div>
        </>
      ) : (
        <div className="flex items-center justify-between gap-3">
          <span className="flex min-w-0 items-center gap-1.5 text-[12px] text-gray-10">
            {commentCount > 0 ? (
              <>
                <ChatCircleIcon size={13} className="shrink-0" />
                <span className="truncate">
                  {commentCount} open comment{commentCount === 1 ? "" : "s"} go
                  with your answer
                </span>
              </>
            ) : (
              <span className="truncate">
                Open it to read it and comment on it
              </span>
            )}
          </span>
          <span className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={submitting}
              onClick={() => setShowFeedback(true)}
            >
              Request changes
            </Button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              loading={submitting}
              disabled={submitting}
              onClick={() => respond("approve")}
            >
              {commentCount > 0
                ? "Accept with comments"
                : "Approve and continue"}
            </Button>
          </span>
        </div>
      )}
    </div>
  );
}
