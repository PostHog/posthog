import { CheckCircleIcon, XCircleIcon } from "@phosphor-icons/react";
import { PI_SESSION_CONTROLLER } from "@posthog/core/pi-runtime/identifiers";
import type { PiSessionController } from "@posthog/core/pi-runtime/piSessionController";
import { useService } from "@posthog/di/react";
import { Button, Textarea } from "@posthog/quill";
import { buildAgentFlowRespondCommand } from "@posthog/shared";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

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
  const resolvedApproved = toolCall.status === "completed";
  const resolvedRejected = toolCall.status === "failed";
  const pending = !resolvedApproved && !resolvedRejected;

  const respond = (outcome: "approve" | "reject", reason?: string) => {
    if (!taskId || !approvalId || submitting) {
      return;
    }
    setSubmitting(true);
    void controller
      .submit(
        taskId,
        buildAgentFlowRespondCommand(approvalId, outcome, reason),
        false,
        "steer",
      )
      .catch(() => {
        setSubmitting(false);
      });
  };

  if (!pending) {
    return (
      <div className="my-2 flex items-center gap-2 text-[13px]">
        {resolvedApproved ? (
          <>
            <CheckCircleIcon size={14} weight="fill" className="text-green-9" />
            <span className="text-green-11">{text || "Handoff approved."}</span>
          </>
        ) : (
          <>
            <XCircleIcon size={14} weight="fill" className="text-gray-9" />
            <span className="text-gray-11">
              {text || "Handoff sent back for changes."}
            </span>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="my-3 flex flex-col gap-3 rounded-lg border border-gray-5 bg-gray-2 p-3">
      <div className="flex flex-col gap-1">
        <span className="font-medium text-[12px] text-gray-11">
          Handoff ready for review
        </span>
        <span className="text-[12px] text-gray-10">
          Approve it to continue the flow, or send it back with feedback.
        </span>
      </div>
      {text ? (
        <div className="chat-markdown max-h-[50vh] overflow-y-auto rounded-md border border-gray-4 bg-gray-1 px-3 py-2 text-[13px] text-gray-12">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
      ) : null}
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
              disabled={submitting || !feedback.trim()}
              onClick={() => respond("reject", feedback)}
            >
              Send for revision
            </Button>
          </div>
        </>
      ) : (
        <div className="flex items-center justify-end gap-2">
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
            Approve and continue
          </Button>
        </div>
      )}
    </div>
  );
}
