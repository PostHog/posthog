import { ChannelHeader } from "@posthog/ui/features/canvas/components/ChannelHeader";
import { SpaceMembersSettings } from "@posthog/ui/features/canvas/components/SpaceMembersSettings";
import { SpaceRepositories } from "@posthog/ui/features/canvas/components/SpaceRepositories";
import { SpaceVisibility } from "@posthog/ui/features/canvas/components/SpaceVisibility";
import { useChannelMembers } from "@posthog/ui/features/canvas/hooks/useChannelMembers";
import {
  type Channel,
  useChannels,
} from "@posthog/ui/features/canvas/hooks/useChannels";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { SettingsSection } from "@posthog/ui/features/settings/components/SettingsCard";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import {
  PageHeader,
  PageHeaderDescription,
  PageHeaderHeading,
  PageHeaderTitle,
} from "@posthog/ui/primitives/PageHeader";
import { useMemo } from "react";

function isShared(
  channel: Channel,
): channel is Channel & { channelType: "public" | "private" } {
  return channel.channelType !== "personal";
}

function memberCountLabel(count: number): string {
  return count === 1 ? "1 member" : `${count} members`;
}

export function SpaceSettings({ channelId }: { channelId: string }) {
  const { channels, isLoading } = useChannels();
  const { channels: taskChannels, isLoading: tasksLoading } = useTaskChannels();
  const channel = channels.find((item) => item.id === channelId);
  const taskChannel = taskChannels.find((item) => item.id === channelId);
  const header = useMemo(
    () => <ChannelHeader channelId={channelId} page="settings" />,
    [channelId],
  );
  useSetHeaderContent(header);
  const isPrivate = channel?.channelType === "private";
  const { members } = useChannelMembers(isPrivate ? channelId : null);

  if (isLoading || tasksLoading)
    return (
      <p className="p-6 text-muted-foreground text-sm">Loading settings…</p>
    );
  if (!channel || !taskChannel)
    return (
      <p className="p-6 text-muted-foreground text-sm">
        This space is unavailable. Choose another space from the sidebar.
      </p>
    );

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader>
        <PageHeaderHeading>
          <PageHeaderTitle>Settings</PageHeaderTitle>
          <PageHeaderDescription>
            Repositories and who can see this space. Changes save as you make
            them.
          </PageHeaderDescription>
        </PageHeaderHeading>
      </PageHeader>
      <div className="flex max-w-[800px] flex-col gap-7 px-6 py-5">
        <SettingsSection
          label="Repositories"
          description="Sessions in this space start with these repositories checked out."
        >
          <SpaceRepositories channel={taskChannel} />
        </SettingsSection>
        <SettingsSection label="Access">
          {isShared(channel) ? (
            <SpaceVisibility key={channel.channelType} channel={channel} />
          ) : (
            <p className="text-[12px] text-muted-foreground">
              Only you can see this personal space.
            </p>
          )}
        </SettingsSection>
        {isPrivate && (
          <SettingsSection
            label="Members"
            description="Any member can add or remove people."
            action={
              members.length > 0 ? (
                <span className="text-[12px] text-muted-foreground">
                  {memberCountLabel(members.length)}
                </span>
              ) : null
            }
          >
            <SpaceMembersSettings key={channel.id} channel={channel} />
          </SettingsSection>
        )}
      </div>
    </div>
  );
}
