import type {
  AvailableSuggestedReviewer,
  RepoSelectionArtefact,
  SuggestedReviewer,
  SuggestedReviewerWriteEntry,
} from "@posthog/shared/types";

export interface ReviewerOption {
  uuid: string;
  name: string;
  email: string;
  github_login: string;
  isMe: boolean;
}

function hasRepositoryContent(
  content: unknown,
): content is RepoSelectionArtefact["content"] {
  return (
    typeof content === "object" &&
    content !== null &&
    "repository" in content &&
    typeof content.repository === "string"
  );
}

export function extractRepoSelectionRepository(
  results: { type: string; content: unknown }[] | undefined,
): string | null {
  const artefact = results?.find(
    (entry): entry is RepoSelectionArtefact =>
      entry.type === "repo_selection" && hasRepositoryContent(entry.content),
  );
  return artefact?.content.repository ?? null;
}

export function suggestedReviewerDisplayName(
  reviewer: SuggestedReviewer,
): string {
  if (reviewer.user) {
    const name =
      `${reviewer.user.first_name} ${reviewer.user.last_name}`.trim();
    if (name) return name;
    if (reviewer.user.email) return reviewer.user.email;
  }
  return (
    reviewer.github_name ??
    reviewer.github_login ??
    reviewer.user?.email ??
    "Reviewer"
  );
}

const OTHER_REVIEWER_SOURCE_LABELS = new Set([
  "Code history",
  "Added by teammate",
  "Agent suggestion",
]);

export function suggestedReviewerSourceLabel(
  reviewer: SuggestedReviewer,
): string {
  if (reviewer.source_label) return reviewer.source_label;
  if (reviewer.relevant_commits.length > 0) return "Code history";
  if (reviewer.reason?.startsWith("Added as a reviewer by ")) {
    return "Added by teammate";
  }
  return "Agent suggestion";
}

export function suggestedReviewerExplanation(
  reviewer: SuggestedReviewer,
): string | null {
  if ("explanation" in reviewer) return reviewer.explanation ?? null;
  return reviewer.reason ?? reviewer.relevant_commits[0]?.reason ?? null;
}

export function isScoutSuggestedReviewer(reviewer: SuggestedReviewer): boolean {
  if (reviewer.source_skill !== undefined) {
    return Boolean(
      reviewer.source_skill && reviewer.relevant_commits.length === 0,
    );
  }
  return !OTHER_REVIEWER_SOURCE_LABELS.has(
    suggestedReviewerSourceLabel(reviewer),
  );
}

export interface SuggestedReviewerPersonItem {
  kind: "person";
  key: string;
  reviewer: SuggestedReviewer;
}

export interface SuggestedReviewerReasonGroupItem {
  kind: "reason-group";
  key: string;
  reason: string;
  reviewers: SuggestedReviewer[];
}

export type SuggestedReviewerItem =
  | SuggestedReviewerPersonItem
  | SuggestedReviewerReasonGroupItem;

function suggestedReviewerKey(reviewer: SuggestedReviewer): string {
  return (
    reviewer.user?.uuid ??
    reviewer.user_uuid ??
    reviewer.github_login ??
    reviewer.github_name ??
    reviewer.user?.email ??
    "unknown-reviewer"
  );
}

function suggestedReviewerReasonGroupKey(
  reviewer: SuggestedReviewer,
  reason: string,
): string {
  const isScout = isScoutSuggestedReviewer(reviewer);
  return JSON.stringify([
    "reason-group",
    reason,
    isScout ? "scout" : "other",
    isScout ? null : suggestedReviewerSourceLabel(reviewer),
  ]);
}

export function buildSuggestedReviewerItems(
  reviewers: SuggestedReviewer[],
): SuggestedReviewerItem[] {
  const items: SuggestedReviewerItem[] = [];
  const reasonCounts = new Map<string, number>();
  const reasonGroups = new Map<string, SuggestedReviewerReasonGroupItem>();

  for (const reviewer of reviewers) {
    const reason = suggestedReviewerExplanation(reviewer);
    if (reason) {
      const groupKey = suggestedReviewerReasonGroupKey(reviewer, reason);
      reasonCounts.set(groupKey, (reasonCounts.get(groupKey) ?? 0) + 1);
    }
  }

  for (const reviewer of reviewers) {
    const reason = suggestedReviewerExplanation(reviewer);
    const groupKey = reason
      ? suggestedReviewerReasonGroupKey(reviewer, reason)
      : null;
    if (!reason || !groupKey || reasonCounts.get(groupKey) === 1) {
      items.push({
        kind: "person",
        key: suggestedReviewerKey(reviewer),
        reviewer,
      });
      continue;
    }

    const existing = reasonGroups.get(groupKey);
    if (existing) {
      existing.reviewers.push(reviewer);
    } else {
      const item: SuggestedReviewerReasonGroupItem = {
        kind: "reason-group",
        key: groupKey,
        reason,
        reviewers: [reviewer],
      };
      reasonGroups.set(groupKey, item);
      items.push(item);
    }
  }

  return items;
}

export function extractSuggestedReviewers(
  results: { type: string; content: unknown }[] | undefined,
): SuggestedReviewer[] {
  const artefact = results?.find(
    (
      entry,
    ): entry is { type: "suggested_reviewers"; content: SuggestedReviewer[] } =>
      entry.type === "suggested_reviewers" && Array.isArray(entry.content),
  );
  return artefact?.content ?? [];
}

export function orderSuggestedReviewers(
  reviewers: SuggestedReviewer[],
  currentUserUuid: string | null | undefined,
): SuggestedReviewer[] {
  if (!currentUserUuid) return reviewers;
  const currentUserIndex = reviewers.findIndex(
    (reviewer) => reviewer.user?.uuid === currentUserUuid,
  );
  if (currentUserIndex <= 0) return reviewers;
  return [
    reviewers[currentUserIndex],
    ...reviewers.filter((_, index) => index !== currentUserIndex),
  ];
}

export function buildReviewerOptions(
  reviewers: AvailableSuggestedReviewer[],
  currentUserUuid: string | undefined,
): ReviewerOption[] {
  const seen = new Set<string>();
  const options: ReviewerOption[] = [];

  for (const reviewer of reviewers) {
    if (!reviewer.uuid || seen.has(reviewer.uuid)) continue;
    seen.add(reviewer.uuid);
    options.push({
      uuid: reviewer.uuid,
      name: reviewer.name?.trim() || "",
      email: reviewer.email?.trim() || "",
      github_login: reviewer.github_login?.trim() || "",
      isMe: reviewer.uuid === currentUserUuid,
    });
  }

  options.sort((first, second) => {
    if (first.isMe && !second.isMe) return -1;
    if (!first.isMe && second.isMe) return 1;
    return (first.name || first.email).localeCompare(
      second.name || second.email,
    );
  });

  return options;
}

export function reviewerOptionLabel(reviewer: ReviewerOption): string {
  const base = reviewer.name || reviewer.email || "Unknown user";
  return reviewer.isMe ? `${base} (Me)` : base;
}

export function reviewerMatchesAvailable(
  reviewer: SuggestedReviewer,
  available: AvailableSuggestedReviewer,
): boolean {
  if (reviewer.user?.uuid && reviewer.user.uuid === available.uuid) {
    return true;
  }
  return (
    !!reviewer.github_login &&
    !!available.github_login &&
    reviewer.github_login.toLowerCase() === available.github_login.toLowerCase()
  );
}

export function toSuggestedReviewerWriteContent(
  reviewers: SuggestedReviewer[],
): SuggestedReviewerWriteEntry[] {
  return reviewers
    .map((reviewer): SuggestedReviewerWriteEntry | null => {
      const userUuid = reviewer.user_uuid ?? reviewer.user?.uuid;
      if (userUuid) return { user_uuid: userUuid };
      if (reviewer.github_login) return { github_login: reviewer.github_login };
      return null;
    })
    .filter((entry): entry is SuggestedReviewerWriteEntry => entry !== null);
}

function hasActionabilityExplanation(
  content: unknown,
): content is { explanation: string } {
  return (
    typeof content === "object" &&
    content !== null &&
    "explanation" in content &&
    typeof content.explanation === "string"
  );
}

/**
 * Why research reached its latest actionability verdict. The judgment is
 * rewritten on every research pass, so the newest artefact is the one that
 * describes the report's current state.
 */
export function extractActionabilityExplanation(
  results: { type: string; content: unknown; created_at: string }[] | undefined,
): string | null {
  const latest = (results ?? [])
    .filter((entry) => entry.type === "actionability_judgment")
    .sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    )
    .at(-1);
  if (!latest || !hasActionabilityExplanation(latest.content)) return null;
  return latest.content.explanation.trim() || null;
}
