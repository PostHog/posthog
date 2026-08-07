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
  return reviewer.github_name ?? reviewer.github_login;
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
      if (reviewer.github_login) return { github_login: reviewer.github_login };
      if (reviewer.user?.uuid) return { user_uuid: reviewer.user.uuid };
      return null;
    })
    .filter((entry): entry is SuggestedReviewerWriteEntry => entry !== null);
}

const AVATAR_PALETTE = [
  "bg-(--orange-9) text-white",
  "bg-(--blue-9) text-white",
  "bg-(--purple-9) text-white",
  "bg-(--green-9) text-white",
  "bg-(--pink-9) text-white",
  "bg-(--teal-9) text-white",
] as const;

export function reviewerAvatarToneClass(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash + seed.charCodeAt(i) * (i + 1)) % 9973;
  }
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length];
}

export function reviewerInitials(
  name: string | null | undefined,
  email: string | null | undefined,
): string {
  const trimmedName = name?.trim() ?? "";
  if (trimmedName) {
    const parts = trimmedName.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) {
      return `${parts[0][0] ?? ""}${parts[parts.length - 1][0] ?? ""}`.toUpperCase();
    }
    return trimmedName.slice(0, 2).toUpperCase();
  }

  const trimmedEmail = email?.trim() ?? "";
  if (trimmedEmail) {
    const local = trimmedEmail.split("@")[0] ?? trimmedEmail;
    return local.slice(0, 2).toUpperCase();
  }

  return "??";
}
