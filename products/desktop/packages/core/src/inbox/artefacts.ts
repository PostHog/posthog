import type {
  RepoSelectionArtefact,
  SuggestedReviewer,
} from "@posthog/shared/types";

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
