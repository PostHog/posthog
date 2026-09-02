import { useReviewNavigationStore } from "@posthog/ui/features/code-review/reviewNavigationStore";

/** Open a PR in the task's in-app review pane. Callers that also offer an
 *  "open on GitHub" affordance pair this with `openExternalUrl`. */
export function openPrInReview(taskId: string, safeUrl: string): void {
  const { setSelectedPrUrl, setReviewMode } =
    useReviewNavigationStore.getState();
  setSelectedPrUrl(taskId, safeUrl);
  setReviewMode(taskId, "split");
}
