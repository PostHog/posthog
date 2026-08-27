import {
  ArrowUUpLeftIcon,
  CheckCircleIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import type { AgentFlowReview } from "@posthog/shared";

function outcomeLine(approved: boolean, commentCount: number): string {
  const base = approved ? "Approved" : "Sent back for changes";
  if (commentCount === 0) {
    return base;
  }
  return `${base} with ${commentCount} comment${commentCount === 1 ? "" : "s"}`;
}

/** How a finished review reads back: the decision, then what the reader said. */
export function FlowReviewOutcome({
  approved,
  review,
  fallbackText,
}: {
  approved: boolean;
  review: AgentFlowReview | null;
  fallbackText: string;
}) {
  if (!review) {
    return (
      <div className="my-2 flex items-center gap-2 text-[13px]">
        {approved ? (
          <CheckCircleIcon size={14} weight="fill" className="text-green-9" />
        ) : (
          <XCircleIcon size={14} weight="fill" className="text-gray-9" />
        )}
        <span
          className={`line-clamp-2 ${approved ? "text-green-11" : "text-gray-11"}`}
        >
          {fallbackText ||
            (approved ? "Handoff approved." : "Handoff sent back for changes.")}
        </span>
      </div>
    );
  }

  const note = review.note?.trim();

  return (
    <div className="my-2 flex max-w-3xl flex-col gap-1.5">
      <div className="flex items-center gap-2 text-[13px]">
        {approved ? (
          <CheckCircleIcon size={14} weight="fill" className="text-green-9" />
        ) : (
          <ArrowUUpLeftIcon size={14} className="text-gray-10" />
        )}
        <span className={approved ? "text-green-11" : "text-gray-11"}>
          {outcomeLine(approved, review.comments.length)}
        </span>
      </div>
      {note ? (
        <p className="ml-[22px] text-[12px] text-gray-11">{note}</p>
      ) : null}
      {review.comments.length > 0 ? (
        <ul className="ml-[22px] flex flex-col gap-1.5">
          {review.comments.map((comment, index) => (
            <li
              // biome-ignore lint/suspicious/noArrayIndexKey: a review is a fixed list
              key={index}
              className="flex flex-col gap-0.5 border-gray-5 border-l pl-2"
            >
              {comment.quote ? (
                <span className="line-clamp-1 text-[11px] text-gray-9 italic">
                  {comment.quote}
                </span>
              ) : null}
              <span className="line-clamp-2 text-[12px] text-gray-11">
                {comment.body}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
