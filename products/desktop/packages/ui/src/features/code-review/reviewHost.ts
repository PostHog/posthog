import type { Task } from "@posthog/shared/domain-types";
import type { ReactNode } from "react";

export interface ReviewHost {
  diffWorkerFactory(): Worker;
  /** The list of a review's files, shown beside the diff when there is room. */
  renderFileBrowser(task: Task): ReactNode;
}

export const REVIEW_HOST = Symbol.for("posthog.ui.ReviewHost");
