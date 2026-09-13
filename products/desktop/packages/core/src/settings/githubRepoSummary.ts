import { POSTHOG_GITHUB_APP_URL } from "../integrations/githubApp";

export function summarizeReposByOwner(
  repositories: readonly string[],
): { owner: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const repo of repositories) {
    const owner = repo.includes("/") ? (repo.split("/", 1)[0] ?? repo) : repo;
    counts.set(owner, (counts.get(owner) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([owner, count]) => ({ owner, count }))
    .sort((a, b) => b.count - a.count || a.owner.localeCompare(b.owner));
}

export interface GithubInstallationAccount {
  type?: string | null;
  name?: string | null;
}

export interface GithubInstallationLike {
  installation_id: string | number;
  account?: GithubInstallationAccount | null;
}

export function githubInstallationSettingsUrl(
  integration: GithubInstallationLike,
): string {
  const accountType = integration.account?.type;
  if (
    typeof accountType === "string" &&
    accountType.toLowerCase() === "organization"
  ) {
    return POSTHOG_GITHUB_APP_URL;
  }
  return `https://github.com/settings/installations/${integration.installation_id}`;
}

export type GithubRepoAccessKind = "all" | "selected" | "empty" | "unknown";

export interface GithubRepoAccessInput {
  /** GitHub's `repository_selection` for the installation, when the row carries it. */
  selection: string | null | undefined;
  /** Total repositories the installation can see, when the API reported one. */
  total: number | null | undefined;
  repos: readonly string[];
  accountLabel?: string | null;
}

export interface GithubRepoAccessSummary {
  kind: GithubRepoAccessKind;
  label: string;
}

function repositoryNoun(count: number): string {
  return count === 1 ? "repository" : "repositories";
}

/**
 * One line describing what an installation can see. "all" is summarized rather than listed:
 * an org with hundreds of repositories reads better as a count than as a truncated list.
 */
export function describeGithubRepoAccess(
  input: GithubRepoAccessInput,
): GithubRepoAccessSummary {
  const account = input.accountLabel?.trim() || "this installation";
  if (input.selection === "all") {
    const suffix = input.total != null ? ` (${input.total})` : "";
    return { kind: "all", label: `All repositories in ${account}${suffix}` };
  }
  const count = input.repos.length;
  if (count === 0) {
    return { kind: "empty", label: "No repositories accessible" };
  }
  if (input.selection === "selected") {
    return {
      kind: "selected",
      label: `${count} selected ${repositoryNoun(count)}`,
    };
  }
  return {
    kind: "unknown",
    label: `${count} ${repositoryNoun(count)} accessible`,
  };
}

/**
 * The account name shown for an installation. A blank or purely numeric name is the
 * placeholder written when GitHub failed to return the account at connect time, so it is
 * replaced with a label that says what the number is.
 */
export function formatGithubAccountLabel(
  account: GithubInstallationAccount | null | undefined,
  installationId: string | number,
): string {
  const name = account?.name?.trim() ?? "";
  if (!name || /^\d+$/.test(name)) {
    return `GitHub installation ${installationId}`;
  }
  return name;
}

export function formatRepoPreview(
  repos: readonly string[],
  previewCount = 3,
): string {
  const preview = repos.slice(0, previewCount).join(", ");
  const remainder = repos.length - previewCount;
  return remainder > 0 ? `${preview} and ${remainder} more` : preview;
}
