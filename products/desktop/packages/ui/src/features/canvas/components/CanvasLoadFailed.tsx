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

export function CanvasLoadFailed({
  error,
  retrying = false,
  onRetry,
}: {
  error: { message: string } | null;
  retrying?: boolean;
  onRetry: () => void;
}) {
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
        <Button
          variant="primary"
          size="default"
          loading={retrying}
          onClick={onRetry}
        >
          Try again
        </Button>
      </EmptyContent>
    </Empty>
  );
}
