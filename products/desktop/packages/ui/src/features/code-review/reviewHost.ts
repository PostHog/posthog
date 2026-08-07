import type { Task } from "@posthog/shared/domain-types";
import type { ReactNode } from "react";

export interface ReviewHost {
  diffWorkerFactory(): Worker;
  renderExpandedSidebar(task: Task): ReactNode;
}

export const REVIEW_HOST = Symbol.for("posthog.ui.ReviewHost");
