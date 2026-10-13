import type { TaskChannel } from "@posthog/shared/domain-types";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { useUpdateTaskChannelRepositories } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { RepositoriesField } from "@posthog/ui/features/integrations/components/RepositoriesField";
import { SettingsCard } from "@posthog/ui/features/settings/components/SettingsCard";
import { Spinner } from "@posthog/ui/primitives/Spinner";

export function SpaceRepositories({ channel }: { channel: TaskChannel }) {
  const update = useUpdateTaskChannelRepositories();
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const canEdit = currentUser?.id === channel.created_by?.id;

  return (
    <SettingsCard>
      <div className="flex flex-col gap-2 px-3.5 py-3">
        <RepositoriesField
          selected={channel.repositories ?? []}
          integrationId={channel.github_integration ?? null}
          disabled={!canEdit || update.isPending}
          onChange={(repositories, githubIntegration) =>
            update.mutate({
              channelId: channel.id,
              githubIntegration,
              repositories,
            })
          }
        />
        {update.isPending && (
          <span className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Spinner size="sm" aria-hidden="true" /> Saving…
          </span>
        )}
        {update.error && (
          <span className="text-[12px] text-red-11">
            Couldn't save. Try again.
          </span>
        )}
        {!canEdit && (
          <span className="text-[12px] text-muted-foreground">
            Only the space creator can change repositories.
          </span>
        )}
      </div>
    </SettingsCard>
  );
}
