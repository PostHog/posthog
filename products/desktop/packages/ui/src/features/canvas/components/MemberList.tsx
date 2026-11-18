import type { UserBasic } from "@posthog/shared/domain-types";
import { MemberRow } from "@posthog/ui/features/canvas/components/MemberRow";
import { SettingsCard } from "@posthog/ui/features/settings/components/SettingsCard";

export function MemberList({
  members,
  currentUser = null,
  onRemove,
  disabled,
}: {
  members: UserBasic[];
  currentUser?: UserBasic | null;
  onRemove: (id: number) => void;
  disabled?: boolean;
}) {
  const others = members.filter((member) => member.id !== currentUser?.id);
  return (
    <SettingsCard>
      {currentUser && <MemberRow member={currentUser} tag="You" />}
      {others.map((member) => (
        <MemberRow
          key={member.id}
          member={member}
          disabled={disabled}
          onRemove={() => onRemove(member.id)}
        />
      ))}
    </SettingsCard>
  );
}
