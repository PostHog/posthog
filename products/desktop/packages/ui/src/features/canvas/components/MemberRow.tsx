import { XIcon } from "@phosphor-icons/react";
import { Badge, Button } from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";

export function MemberRow({
  member,
  tag,
  onRemove,
  disabled,
}: {
  member: UserBasic;
  tag?: string;
  onRemove?: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex min-h-11 items-center gap-3 px-3.5 py-2">
      <UserAvatar user={member} size="sm" className="shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col leading-snug">
        <span className="truncate font-medium text-[13px] text-foreground">
          {userDisplayName(member)}
        </span>
        <span className="truncate text-[12px] text-muted-foreground">
          {member.email}
        </span>
      </div>
      {tag && <Badge variant="default">{tag}</Badge>}
      {onRemove && (
        <Button
          variant="default"
          size="icon-sm"
          aria-label={`Remove ${userDisplayName(member)}`}
          disabled={disabled}
          onClick={onRemove}
        >
          <XIcon size={14} />
        </Button>
      )}
    </div>
  );
}
