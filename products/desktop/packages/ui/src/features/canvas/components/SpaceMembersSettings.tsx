import type { UserBasic } from "@posthog/shared/domain-types";
import { MemberRow } from "@posthog/ui/features/canvas/components/MemberRow";
import { MemberSearch } from "@posthog/ui/features/canvas/components/MemberSearch";
import {
  useChannelMembers,
  useSetChannelMembers,
} from "@posthog/ui/features/canvas/hooks/useChannelMembers";
import type { Channel } from "@posthog/ui/features/canvas/hooks/useChannels";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { SettingsCard } from "@posthog/ui/features/settings/components/SettingsCard";
import { toast } from "@posthog/ui/primitives/toast";

export function SpaceMembersSettings({ channel }: { channel: Channel }) {
  const { members, isLoading, error } = useChannelMembers(channel.id);
  const { setMembers, isSaving } = useSetChannelMembers(channel.id);
  const creatorId = channel.createdBy?.id ?? null;
  const memberIds = members.map((member) => member.id);

  const commit = async (ids: number[], failure: string) => {
    try {
      await setMembers(ids);
    } catch (error) {
      toast.error(failure, {
        description: error instanceof Error ? error.message : String(error),
      });
    }
  };
  const addMember = (id: number) =>
    void commit([...memberIds, id], "Couldn't add this person. Try again.");
  const removeMember = (member: UserBasic) =>
    void commit(
      memberIds.filter((id) => id !== member.id),
      `Couldn't remove ${userDisplayName(member)}. Try again.`,
    );

  if (isLoading)
    return (
      <p className="text-[12px] text-muted-foreground">Loading members…</p>
    );
  if (error)
    return (
      <p role="alert" className="text-[12px] text-red-11">
        Couldn't load members. Reload to try again.
      </p>
    );

  return (
    <div className="flex flex-col gap-2">
      <MemberSearch
        excludeIds={memberIds}
        onPick={addMember}
        disabled={isSaving}
        placeholder="Add people…"
      />
      <SettingsCard>
        {members.map((member) => (
          <MemberRow
            key={member.id}
            member={member}
            tag={member.id === creatorId ? "Creator" : undefined}
            disabled={isSaving}
            onRemove={
              member.id === creatorId ? undefined : () => removeMember(member)
            }
          />
        ))}
      </SettingsCard>
    </div>
  );
}
