import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
  Skeleton,
} from "@posthog/quill";
import type { ReactNode } from "react";

const SKELETON_ROWS = [0, 1, 2];

/**
 * The states a card list passes through before it has cards: still loading,
 * failed to load, and nothing to show. The signals list and the memory list
 * both stand on this, so they hold the same shape as each other.
 */
export function ScoutListBody({
  loading,
  failed,
  empty,
  errorMessage,
  emptyMessage,
  onRetry,
  children,
}: {
  loading: boolean;
  failed: boolean;
  empty: boolean;
  errorMessage: string;
  emptyMessage: string;
  onRetry: () => void;
  children: ReactNode;
}) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {SKELETON_ROWS.map((row) => (
          <Skeleton key={row} className="h-14 w-full" />
        ))}
      </div>
    );
  }

  if (failed) {
    return (
      <Empty className="py-10">
        <EmptyHeader>
          <EmptyDescription>{errorMessage}</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button type="button" variant="outline" size="sm" onClick={onRetry}>
            Retry
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  if (empty) {
    return (
      <Empty className="py-10">
        <EmptyHeader>
          <EmptyTitle>{emptyMessage}</EmptyTitle>
        </EmptyHeader>
      </Empty>
    );
  }

  return <>{children}</>;
}
