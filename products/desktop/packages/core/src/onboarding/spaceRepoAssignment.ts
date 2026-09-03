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
 * Matched by account name, falling back to a sole integration. Returns null
 * rather than guessing between several that do not match the owner.
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

export interface SpaceRepoAssignmentFlags {
  personalCreated: boolean;
  generalCreated: boolean;
}

/**
 * Which spaces the onboarding repo pick becomes the default for. Re-onboarding
 * (wiped local storage) must not clobber what a user or their team set up, and
 * an empty inherited #general is not the same signal as a just-created one:
 * a teammate may have emptied it on purpose.
 */
export function planSpaceRepoAssignments(
  channels: AssignableChannel[],
  flags: SpaceRepoAssignmentFlags,
): string[] {
  const targets: string[] = [];
  const personal = channels.find((channel) => isPersonalChannel(channel));
  if (
    personal &&
    (flags.personalCreated || (personal.repositories ?? []).length === 0)
  ) {
    targets.push(personal.id);
  }
  const general = channels.find((channel) => isGeneralChannel(channel));
  if (
    general &&
    flags.generalCreated &&
    (general.repositories ?? []).length === 0
  ) {
    targets.push(general.id);
  }
  return targets;
}
