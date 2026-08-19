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

export interface SpaceRepoAssignmentFlags {
  personalCreated: boolean;
  generalCreated: boolean;
}

/**
 * Which spaces the onboarding repo pick becomes the default for. A space that
 * existed before this onboarding and carries repositories keeps its config: a
 * re-run of onboarding (wiped local storage) must not clobber what the user or
 * their team set up. An empty pre-existing personal space is still safe to
 * fill; an inherited #general is not, because a teammate may have emptied it
 * on purpose.
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
