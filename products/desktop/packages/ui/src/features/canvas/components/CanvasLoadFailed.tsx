import { WarningIcon } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";

/**
 * Shown when the canvas request itself failed, as opposed to resolving to nothing.
 *
 * Kept separate from `CanvasNotFound` because the next action differs: a failed request is
 * worth retrying, a missing canvas never is.
 */
export function CanvasLoadFailed({
  error,
  onRetry,
}: {
  error: { message: string } | null;
  onRetry: () => void;
}) {
  // The title already says it failed, so the message leads as its own sentence rather than
  // being introduced again. Trailing punctuation varies by error, so normalize it.
  const detail = error?.message?.trim().replace(/\.+$/, "");
  const nextStep =
    "Try again, and if it keeps happening check your connection.";

  return (
    <Empty className="h-full border-0">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <WarningIcon size={24} />
        </EmptyMedia>
        <EmptyTitle>Couldn't load this canvas</EmptyTitle>
        <EmptyDescription>
          {detail ? `${detail}. ${nextStep}` : nextStep}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button variant="primary" size="default" onClick={onRetry}>
          Try again
        </Button>
      </EmptyContent>
    </Empty>
  );
}
