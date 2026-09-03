import { WarningCircleIcon } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useCallback, useState } from "react";

interface InboxLoadFailureProps {
  /** Plural noun for the list that failed to load, e.g. "reports". */
  noun: string;
  onRetry: () => Promise<unknown>;
}

/**
 * Shown when an inbox list request fails and no page is loaded. Without it the
 * list falls through to its empty state, which tells the reader there is
 * nothing to review when in fact we could not ask.
 */
export function InboxLoadFailure({ noun, onRetry }: InboxLoadFailureProps) {
  const { retry, isRetrying } = useRetryControl(onRetry);

  return (
    <Empty className="mx-auto max-w-md flex-none border-0 py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <WarningCircleIcon size={24} />
        </EmptyMedia>
        <EmptyTitle>Couldn't load {noun}</EmptyTitle>
        <EmptyDescription>
          Check your connection, then try again.
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        <Button
          variant="outline"
          size="default"
          loading={isRetrying}
          onClick={retry}
        >
          Retry
        </Button>
      </EmptyContent>
    </Empty>
  );
}

/**
 * Shown above a list that still holds reports from an earlier request while the
 * current one fails. The list keeps polling, so without this the reader sees
 * data that quietly stopped updating.
 */
export function InboxStaleListNotice({ noun, onRetry }: InboxLoadFailureProps) {
  const { retry, isRetrying } = useRetryControl(onRetry);

  return (
    <output className="flex flex-wrap items-center justify-between gap-2 rounded-(--radius-2) border border-(--gray-5) bg-(--gray-2) px-3 py-2">
      <div className="flex min-w-0 items-center gap-2">
        <WarningCircleIcon size={16} className="shrink-0 text-gray-10" />
        <span className="text-gray-11 text-sm">
          The last refresh failed. These {noun} could be out of date.
        </span>
      </div>
      <Button variant="outline" size="sm" loading={isRetrying} onClick={retry}>
        Retry
      </Button>
    </output>
  );
}

/**
 * The inbox lists poll every few seconds, so the query's own refetch flag
 * cannot drive the control: it goes true on each background poll as well.
 */
function useRetryControl(onRetry: () => Promise<unknown>): {
  retry: () => void;
  isRetrying: boolean;
} {
  const [isRetrying, setIsRetrying] = useState(false);

  const retry = useCallback(() => {
    setIsRetrying(true);
    void onRetry().finally(() => setIsRetrying(false));
  }, [onRetry]);

  return { retry, isRetrying };
}
