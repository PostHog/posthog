import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { integrationKeys } from "@posthog/core/integrations/repositoryKeys";
import {
  classifyIntegrations,
  type Integration,
} from "@posthog/core/integrations/selectors";
import {
  planSpaceRepoAssignments,
  resolveRepoIntegrationId,
} from "@posthog/core/onboarding/spaceRepoAssignment";
import type {
  ProvisionedTaskChannels,
  TaskChannel,
} from "@posthog/shared/domain-types";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { TASK_CHANNELS_QUERY_KEY } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import type { QueryClient } from "@tanstack/react-query";

type OnboardingRepositoryClient = Pick<
  PostHogAPIClient,
  "getIntegrations" | "updateTaskChannelRepositories"
>;

interface SaveOnboardingRepositoryInput {
  client: OnboardingRepositoryClient;
  provisioned: ProvisionedTaskChannels;
  queryClient: QueryClient;
  repository: string;
}

/** Save the onboarding repository in each empty system space and its cache. */
export async function saveOnboardingRepository({
  client,
  provisioned,
  queryClient,
  repository,
}: SaveOnboardingRepositoryInput): Promise<number> {
  queryClient.setQueryDefaults(TASK_CHANNELS_QUERY_KEY, {
    meta: AUTH_SCOPED_QUERY_META,
  });
  queryClient.setQueryData(TASK_CHANNELS_QUERY_KEY, provisioned.channels);

  const integrations = await queryClient.fetchQuery({
    queryKey: integrationKeys.list(),
    queryFn: () => client.getIntegrations() as Promise<Integration[]>,
    staleTime: 60_000,
    meta: AUTH_SCOPED_QUERY_META,
  });
  const integrationId = resolveRepoIntegrationId(
    repository,
    classifyIntegrations(integrations).githubIntegrations,
  );
  if (integrationId === null) return 0;

  const targetIds = planSpaceRepoAssignments(provisioned.channels, {
    personalCreated: provisioned.personal_created,
    generalCreated: provisioned.general_created,
  });
  const updatedChannels = await Promise.all(
    targetIds.map((channelId) =>
      client.updateTaskChannelRepositories(channelId, integrationId, [
        repository,
      ]),
    ),
  );
  const updatedById = new Map(
    updatedChannels.map((channel) => [channel.id, channel]),
  );
  queryClient.setQueryData<TaskChannel[]>(TASK_CHANNELS_QUERY_KEY, (channels) =>
    channels?.map((channel) => updatedById.get(channel.id) ?? channel),
  );

  return updatedChannels.length;
}
