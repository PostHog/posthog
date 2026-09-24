import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { SignalReportsQueryParams } from "@posthog/shared/types";
import type { InboxScope } from "./reportMembership";

export const CURRENT_OWNERSHIP_FLAG = "signals-current-ownership";

async function allPages<T>(
  load: (offset: number) => Promise<{ results: T[]; next?: string | null }>,
): Promise<T[]> {
  const results: T[] = [];
  for (;;) {
    const page = await load(results.length);
    results.push(...page.results);
    if (!page.next || page.results.length === 0) return results;
  }
}

export async function loadRoutingCatalogue(client: PostHogAPIClient) {
  const [domains, teams, preferences, batches] = await Promise.all([
    allPages((offset) => client.getRoutingDomains(offset)),
    client.getRoutingTeams(),
    allPages((offset) => client.getRoutingPreferences(offset)),
    client.getRoutingBatches(),
  ]);
  return {
    domains,
    teams,
    preferences,
    batches: batches.results,
  };
}

export function ownershipScopeParams(
  scope: InboxScope,
): SignalReportsQueryParams {
  if (scope === "for-you") return { scope: "for_me" };
  if (scope === "unclassified") return { scope: "unclassified" };
  if (scope.startsWith("team:"))
    return { scope: "team", owning_role_id: scope.slice(5) };
  if (scope.startsWith("domain:"))
    return { scope: "domain", domain_id: scope.slice(7) };
  if (scope.startsWith("teammate:"))
    return { scope: "teammate", teammate_uuid: scope.slice(9) };
  return { scope: "entire_project" };
}
