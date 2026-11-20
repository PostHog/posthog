import type { PrActionType, PrCheck } from "@posthog/shared";

export type PrVisualIcon = "merged" | "pull-request";

export interface PrAction {
  id: PrActionType;
  label: string;
}

export interface PrVisualConfig {
  color: "gray" | "green" | "red" | "purple";
  /**
   * Draw the badge as a solid, brand-coloured control rather than a tinted one.
   * Only a draft takes it: every other state reports what happened to the PR,
   * while a draft is the one waiting on someone to press "Ready for review".
   */
  solid?: boolean;
  icon: PrVisualIcon;
  label: string;
  actions: PrAction[];
}

export function getPrVisualConfig(
  state: string,
  merged: boolean,
  draft: boolean,
): PrVisualConfig {
  if (merged) {
    return {
      color: "purple",
      icon: "merged",
      label: "Merged",
      actions: [],
    };
  }
  if (state === "closed") {
    return {
      color: "red",
      icon: "pull-request",
      label: "Closed",
      actions: [{ id: "reopen", label: "Reopen PR" }],
    };
  }
  if (draft) {
    return {
      color: "gray",
      solid: true,
      icon: "pull-request",
      label: "Draft",
      actions: [
        { id: "ready", label: "Ready for review" },
        { id: "close", label: "Close PR" },
      ],
    };
  }
  return {
    color: "green",
    icon: "pull-request",
    label: "Open",
    actions: [
      { id: "draft", label: "Convert to draft" },
      { id: "close", label: "Close PR" },
    ],
  };
}

export function getOptimisticPrState(action: PrActionType) {
  switch (action) {
    case "close":
      return { state: "closed", merged: false, draft: false };
    case "reopen":
      return { state: "open", merged: false, draft: false };
    case "ready":
      return { state: "open", merged: false, draft: false };
    case "draft":
      return { state: "open", merged: false, draft: true };
  }
}

export const PR_ACTION_LABELS: Record<PrActionType, string> = {
  close: "PR closed",
  reopen: "PR reopened",
  ready: "PR marked as ready for review",
  draft: "PR converted to draft",
};

export function parsePrNumber(prUrl: string): string | undefined {
  return prUrl.match(/\/pull\/(\d+)/)?.[1];
}

export interface GitlabMergeRequestRef {
  /** Full project path, which can include nested groups. */
  project: string;
  iid: number;
}

// Coding tasks run only against gitlab.com, so a self-managed GitLab host is not linked.
const GITLAB_HOSTS = new Set(["gitlab.com", "www.gitlab.com"]);
const MERGE_REQUEST_PATH =
  /^\/((?:[^/]+\/)+[^/]+)\/-\/merge_requests\/(\d+)(?:\/|$)/;

/**
 * A gitlab.com merge request URL, or null. PR state, checks and actions all go
 * through GitHub, so callers use this to skip them for a merge request.
 */
export function parseGitlabMergeRequestUrl(
  url: string | null | undefined,
): GitlabMergeRequestRef | null {
  if (!url) return null;
  let parsed: URL;
  try {
    parsed = new URL(url.trim());
  } catch {
    return null;
  }
  if (parsed.protocol !== "https:" || !GITLAB_HOSTS.has(parsed.hostname)) {
    return null;
  }
  const match = MERGE_REQUEST_PATH.exec(parsed.pathname);
  if (!match) return null;
  return { project: match[1], iid: Number(match[2]) };
}

// A PR's CI in one line: failing beats running beats passing.
export function summarizePrChecks(
  checks: PrCheck[] | null | undefined,
): { label: string; color: string } | null {
  if (!checks || checks.length === 0) return null;
  let failed = 0;
  let pending = 0;
  let passed = 0;
  for (const check of checks) {
    if (check.bucket === "fail" || check.bucket === "cancel") failed++;
    else if (check.bucket === "pending") pending++;
    else if (check.bucket === "pass") passed++;
  }
  if (failed) {
    return {
      label: `CI failing · ${failed} ${failed === 1 ? "check" : "checks"}`,
      color: "var(--red-11)",
    };
  }
  if (pending) return { label: "CI running", color: "var(--amber-11)" };
  if (passed) return { label: "CI passing", color: "var(--green-11)" };
  return null;
}
