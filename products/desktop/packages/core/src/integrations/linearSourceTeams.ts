import type { ExternalDataSource } from "@posthog/api-client/posthog-client";

/**
 * Linear source only: the Linear team ids Self-driving reads issues from. Absent or an empty
 * list means every team. Declared in `products/signals/backend/contracts.py`; the generated
 * config type is an open object, so the key name only exists here and there.
 */
export const SOURCE_LINEAR_TEAM_IDS_KEY = "linear_team_ids";

/** Anything that is not a list of ids reads as "every team", matching the backend's fallback. */
export function linearTeamIdsFromConfig(
  config: Record<string, unknown> | null | undefined,
): string[] {
  const raw = config?.[SOURCE_LINEAR_TEAM_IDS_KEY];
  return Array.isArray(raw)
    ? raw.filter((id): id is string => typeof id === "string" && id !== "")
    : [];
}

/**
 * The endpoint replaces the config object wholesale, so the whole blob goes back with the team
 * list merged in; a partial object would clobber the steering text.
 */
export function buildLinearTeamIdsConfig(
  baseConfig: Record<string, unknown> | null | undefined,
  teamIds: readonly string[],
): Record<string, unknown> {
  return { ...(baseConfig ?? {}), [SOURCE_LINEAR_TEAM_IDS_KEY]: [...teamIds] };
}

/** Card summary of what the Linear source reads. */
export function linearTeamsSummary(
  config: Record<string, unknown> | null | undefined,
): string {
  const count = linearTeamIdsFromConfig(config).length;
  if (count === 0) return "All teams";
  return `${count} ${count === 1 ? "team" : "teams"}`;
}

/**
 * The Linear connection whose teams the picker offers. The warehouse source records the
 * workspace it syncs, so its connection is the one whose teams match the synced issues.
 * Before a source exists, any Linear connection will do.
 */
export function resolveLinearIntegrationId(
  integrations: readonly { kind: string; id: number | string }[],
  sources: readonly ExternalDataSource[] | null | undefined,
): number | null {
  const linearIntegrations = integrations.filter(
    (integration) => integration.kind === "linear",
  );
  if (linearIntegrations.length === 0) return null;
  const syncedId = sources?.find(
    (source) => source.source_type.toLowerCase() === "linear",
  )?.job_inputs?.linear_integration_id;
  const matched = linearIntegrations.find(
    (integration) => String(integration.id) === String(syncedId),
  );
  return Number(matched?.id ?? linearIntegrations[0].id);
}
