import {
  type ChannelIdentity,
  isGeneralChannel,
  isPersonalChannel,
} from "../canvas/channelName";

export interface AssignableChannel extends ChannelIdentity {
  id: string;
  repositories?: string[];
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
 * space always, and the shared #general space only when this onboarding's
 * provisioning call just created it (the server's general_created flag). An
 * inherited #general is team state, even when its repository list is empty:
 * someone may have emptied it on purpose. The empty check guards the race
 * where a teammate configures the just-created space first.
 */
export function planSpaceRepoAssignments(
  channels: AssignableChannel[],
  generalJustCreated: boolean,
): string[] {
  const targets: string[] = [];
  const personal = channels.find((channel) => isPersonalChannel(channel));
  if (personal) targets.push(personal.id);
  const general = channels.find((channel) => isGeneralChannel(channel));
  if (
    general &&
    generalJustCreated &&
    (general.repositories ?? []).length === 0
  ) {
    targets.push(general.id);
  }
  return targets;
}
