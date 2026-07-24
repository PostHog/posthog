import type { Task } from "@posthog/shared/domain-types";
import { DotsCircleSpinner } from "@posthog/ui/primitives/DotsCircleSpinner";
import { lazy, type ReactNode, Suspense } from "react";

// The code-review surface (ReviewShell, diff rows, comment UI, review hooks) is
// only reached when a review is opened, so it's split out of the initial bundle.
// The underlying diff/highlight libraries stay eager — the transcript uses them.
const ReviewPageLazy = lazy(() =>
  import("./ReviewPage").then((m) => ({ default: m.ReviewPage })),
);
const CloudReviewPageLazy = lazy(() =>
  import("./CloudReviewPage").then((m) => ({ default: m.CloudReviewPage })),
);

function ReviewFallback(): ReactNode {
  return (
    <div className="flex h-full items-center justify-center">
      <DotsCircleSpinner />
    </div>
  );
}

export function LazyReviewPage({ task }: { task: Task }): ReactNode {
  return (
    <Suspense fallback={<ReviewFallback />}>
      <ReviewPageLazy task={task} />
    </Suspense>
  );
}

export function LazyCloudReviewPage({ task }: { task: Task }): ReactNode {
  return (
    <Suspense fallback={<ReviewFallback />}>
      <CloudReviewPageLazy task={task} />
    </Suspense>
  );
}
