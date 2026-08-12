import { useMemo } from "react";
import { useAgentEnvKeys } from "./useAgentEnvKeys";
import { useAgentRevision } from "./useAgentRevision";

const EMPTY: string[] = [];

/**
 * Names of secrets the given revision declares in its spec but the revision
 * doesn't have set yet. Env keys are revision-scoped, so a draft carries its
 * own secret set; for any name in this list the runner will fail at use-site
 * until the author sets it on this revision.
 *
 * Returns the empty list when no revision is targeted (live chat doesn't
 * surface this — drafts are the only place where unset secrets are an
 * authoring blocker).
 */
export function useAgentMissingSecrets(
  idOrSlug: string,
  revisionId: string | null,
): string[] {
  const { data: revision } = useAgentRevision(idOrSlug, revisionId);
  const { data: envKeys } = useAgentEnvKeys(idOrSlug, revisionId);
  return useMemo(() => {
    if (!revisionId) return EMPTY;
    const declared = revision?.spec?.secrets ?? [];
    if (declared.length === 0) return EMPTY;
    const set = new Set(envKeys ?? []);
    const missing = declared.filter((name) => !set.has(name));
    return missing.length === declared.length && envKeys == null
      ? // env-keys query hasn't loaded yet; avoid flashing the card with the
        // full list before we know what's actually set.
        EMPTY
      : missing;
  }, [revisionId, revision, envKeys]);
}
