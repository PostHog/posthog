import type { DiffSource, ResolvedDiffSource } from "./types";

export type { ResolvedDiffSource } from "./types";

export interface ResolveDiffSourceInput {
  configured: DiffSource | null;
  hasLocalChanges: boolean;
  linkedBranch: string | null;
  aheadOfDefault: number;
  prSourceAvailable: boolean;
}

export function resolveDiffSource({
  configured,
  hasLocalChanges,
  linkedBranch,
  aheadOfDefault,
  prSourceAvailable,
}: ResolveDiffSourceInput): ResolvedDiffSource {
  const branchAvailable = !!linkedBranch && aheadOfDefault > 0;

  if (configured === "pr") {
    if (prSourceAvailable) return "pr";
    if (branchAvailable) return "branch";
    return "local";
  }
  if (configured === "branch") {
    return branchAvailable ? "branch" : "local";
  }
  if (configured === "local") {
    return "local";
  }

  if (hasLocalChanges) return "local";
  if (prSourceAvailable) return "pr";
  if (branchAvailable) return "branch";
  return "local";
}
