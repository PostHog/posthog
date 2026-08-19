import {
  type ChannelIdentity,
  isGeneralChannel,
  isPersonalChannel,
} from "../canvas/channelName";

export interface AssignableChannel extends ChannelIdentity {
  id: string;
  repositories?: string[];
  created_by?: { uuid: string } | null;
}

export interface AssignableGithubIntegration {
  id: number;
  config?: { account?: { name?: string | null } | null };
}

/**
 * The team integration that provides an "owner/repo" pick, matched by account
 * name. Falls back to the only integration when there is exactly one, and
 * refuses to guess between several non-matching ones.
 */
export function resolveRepoIntegrationId(
  repo: string,
  integrations: AssignableGithubIntegration[],
): number | null {
  const owner = repo.split("/")[0]?.toLowerCase();
  if (owner) {
    const match = integrations.find(
      (integration) =>
        integration.config?.account?.name?.toLowerCase() === owner,
    );
    if (match) return match.id;
  }
  return integrations.length === 1 ? integrations[0].id : null;
}

/**
 * Which spaces the onboarding repo pick becomes the default for: the personal
 * space always, and the shared #general space only when this user's own
 * onboarding provisioned it (they are its creator) and nobody has configured
 * repositories. A teammate-created #general is team state, even when its
 * repository list is empty: someone may have emptied it on purpose.
 */
export function planSpaceRepoAssignments(
  channels: AssignableChannel[],
  currentUserUuid: string | null | undefined,
): string[] {
  const targets: string[] = [];
  const personal = channels.find((channel) => isPersonalChannel(channel));
  if (personal) targets.push(personal.id);
  const general = channels.find((channel) => isGeneralChannel(channel));
  if (
    general &&
    (general.repositories ?? []).length === 0 &&
    currentUserUuid != null &&
    general.created_by?.uuid === currentUserUuid
  ) {
    targets.push(general.id);
  }
  return targets;
}
