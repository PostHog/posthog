import type {
  ScoutOutputDestinations,
  ScoutSlackDestination,
} from "@posthog/api-client/posthog-client";
import type { SlackMemberOption } from "@posthog/shared/domain-types";

// Mirrors MAX_SCOUT_SLACK_DM_TARGETS on the backend serializer.
export const MAX_SCOUT_SLACK_DM_TARGETS = 5;

export type SlackTargetMode = "channel" | "dm";

/** A member target the picker stores: `member_id|@display-name`. */
export function buildMemberTargetValue(
  memberId: string,
  displayName: string,
): string {
  const handle = displayName.startsWith("@") ? displayName : `@${displayName}`;
  return `${memberId}|${handle}`;
}

export function parseMemberIdFromTargetValue(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  return value.split("|")[0]?.trim() || null;
}

export function parseMemberNameFromTargetValue(
  value: string | null | undefined,
): string | null {
  if (!value) return null;
  // Split once: a display name can itself contain `|` (Slack names are free text).
  const separator = value.indexOf("|");
  if (separator === -1) return null;
  const display = value.slice(separator + 1).trim();
  if (!display) return null;
  return display.startsWith("@") ? display.slice(1) : display;
}

/**
 * Which side of the channel/DM toggle a saved destination sits on. A destination
 * with members is a DM; anything else defaults to channel.
 */
export function deriveSlackTargetMode(
  destination: ScoutSlackDestination | null | undefined,
): SlackTargetMode {
  return destination?.users?.length ? "dm" : "channel";
}

/**
 * Keep the first target per member ID and cap the list, matching the backend's
 * dedupe so the picker never offers to save a list the API would trim.
 */
export function dedupeMemberTargets(
  targets: readonly string[],
  max: number = MAX_SCOUT_SLACK_DM_TARGETS,
): string[] {
  const seen = new Set<string>();
  const deduped: string[] = [];
  for (const target of targets) {
    const memberId = parseMemberIdFromTargetValue(target);
    if (!memberId || seen.has(memberId)) continue;
    seen.add(memberId);
    deduped.push(target);
  }
  return deduped.slice(0, max);
}

/**
 * Include already-selected members the search page did not return, so their
 * chips keep their names instead of falling back to a bare ID.
 */
export function mergeVisibleMembers(
  fetched: readonly SlackMemberOption[],
  selectedTargets: readonly string[],
): SlackMemberOption[] {
  const members = [...fetched];
  const present = new Set(members.map((member) => member.id));
  for (const target of selectedTargets) {
    const id = parseMemberIdFromTargetValue(target);
    if (!id || present.has(id)) continue;
    present.add(id);
    const name = parseMemberNameFromTargetValue(target) ?? id;
    members.push({ id, name, display_name: name });
  }
  return members;
}

/**
 * Fold a new Slack destination into the config's existing destinations. The
 * backend replaces the stored object wholesale, so we carry the webhook pointer
 * forward — a product other than Signals owns it — and drop Slack when null.
 */
export function writeSlackDestination(
  existing: ScoutOutputDestinations | null | undefined,
  slack: ScoutSlackDestination | null,
): ScoutOutputDestinations {
  const next: ScoutOutputDestinations = {};
  if (existing?.webhook) next.webhook = existing.webhook;
  if (slack) next.slack = slack;
  return next;
}

/**
 * Coarse label for analytics: the kind of Slack delivery a scout has, never the
 * member IDs or channel behind it.
 */
export function describeSlackDelivery(
  destinations: ScoutOutputDestinations | null | undefined,
): "dm" | "channel" | "off" {
  const slack = destinations?.slack;
  if (slack?.users?.length) return "dm";
  if (slack?.channel) return "channel";
  return "off";
}
