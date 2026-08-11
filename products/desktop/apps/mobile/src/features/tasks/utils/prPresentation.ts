import {
  getPrVisualConfig,
  type PrVisualConfig,
} from "@posthog/core/git-interaction/prStatus";
import { readPrUrls } from "@posthog/shared";
import { parseGithubIssueUrl } from "@/lib/githubIssueUrl";

/**
 * Mirrors the desktop "merged" PR color (Radix purple-9 family). Theme tokens
 * don't include a purple, and merged-PR purple is recognisable enough that a
 * fixed value works in both light and dark.
 */
export const MERGED_PR_COLOR = "#8e4ec6";

export type PrChipTone = PrVisualConfig["color"];

export interface TaskPrChip {
  /** Canonical PR url, safe to hand to `Linking.openURL`. */
  url: string;
  number: number;
  /** Short row label, e.g. `#2422`. */
  label: string;
}

/**
 * The PR a task row should link to: the first PR url its latest run reported,
 * normalized. Runs can also report issue urls or junk, so anything that isn't
 * a canonical GitHub pull-request url yields no chip rather than a link that
 * lands somewhere unexpected.
 */
export function deriveTaskPrChip(task: {
  latest_run?: { output?: Record<string, unknown> | null } | null;
}): TaskPrChip | null {
  const prUrl = readPrUrls(task.latest_run?.output)[0];
  if (!prUrl) return null;

  const ref = parseGithubIssueUrl(prUrl);
  if (ref?.kind !== "pr") return null;

  return {
    url: ref.normalizedUrl,
    number: ref.number,
    label: `#${ref.number}`,
  };
}

export interface PrChipStatus {
  state: "open" | "closed";
  merged: boolean;
  draft: boolean;
}

export interface PrChipAppearance {
  tone: PrChipTone;
  /** `null` until the PR's live state resolves (private repo, offline, 404). */
  statusLabel: string | null;
}

/**
 * Tone and wording for a chip, from the same rules desktop paints PRs with.
 * An unresolved status stays neutral: a guess would read as a state we never
 * confirmed.
 */
export function getPrChipAppearance(
  status: PrChipStatus | null | undefined,
): PrChipAppearance {
  if (!status) return { tone: "gray", statusLabel: null };
  const config = getPrVisualConfig(status.state, status.merged, status.draft);
  return { tone: config.color, statusLabel: config.label };
}

export function prChipAccessibilityLabel(
  chip: TaskPrChip,
  statusLabel: string | null,
): string {
  return statusLabel
    ? `Open ${statusLabel.toLowerCase()} pull request ${chip.label}`
    : `Open pull request ${chip.label}`;
}
