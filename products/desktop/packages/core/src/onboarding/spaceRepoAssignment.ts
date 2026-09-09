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

/**
 * The onboarding repository becomes the default for empty system spaces.
 * Existing repository settings stay unchanged when onboarding runs again.
 */
export function planSpaceRepoAssignments(
  channels: AssignableChannel[],
): string[] {
  const targets: string[] = [];
  const personal = channels.find((channel) => isPersonalChannel(channel));
  if (personal && (personal.repositories ?? []).length === 0) {
    targets.push(personal.id);
  }
  const general = channels.find((channel) => isGeneralChannel(channel));
  if (general && (general.repositories ?? []).length === 0) {
    targets.push(general.id);
  }
  return targets;
}
