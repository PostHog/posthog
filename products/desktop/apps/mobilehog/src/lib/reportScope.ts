import { buildSuggestedReviewerFilterParam } from "@posthog/core/inbox/reportFiltering";
import type { SignalReportsQueryParams } from "@posthog/shared/domain-types";
import { create } from "zustand";

export type ReportScope = "for-you" | "entire-project";

export const REPORT_SCOPES = [
  { value: "for-you", label: "For you", icon: "person" },
  { value: "entire-project", label: "Entire project", icon: "person.2" },
] as const;

export const useReportScope = create<{
  scope: ReportScope;
  setScope: (scope: ReportScope) => void;
}>((set) => ({
  scope: "for-you",
  setScope: (scope) => set({ scope }),
}));

// Null means "For you" has no reviewer to filter on. The caller must not fall
// back to the whole project then.
export function reportScopeParams(
  scope: ReportScope,
  userUuid: string | null | undefined,
): Pick<SignalReportsQueryParams, "suggested_reviewers"> | null {
  if (scope === "entire-project") return {};
  const reviewers = buildSuggestedReviewerFilterParam(
    userUuid ? [userUuid] : [],
  );
  return reviewers ? { suggested_reviewers: reviewers } : null;
}
