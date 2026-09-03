import { Robot } from "@phosphor-icons/react";
import type { McpGatewayUser } from "@posthog/api-client/posthog-client";
import { Avatar, AvatarFallback, AvatarGroup, cn } from "@posthog/quill";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";

export function gatewayUserName(user: McpGatewayUser): string {
  const name = [user.first_name, user.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
  return name || user.email;
}

const ROBOT_SIZES = {
  sm: { quill: "xs", icon: 12 },
  md: { quill: "sm", icon: 14 },
  lg: { quill: "lg", icon: 22 },
} as const;

export function RobotAvatar({
  size = "md",
  className,
}: {
  size?: keyof typeof ROBOT_SIZES;
  className?: string;
}) {
  const avatarSize = ROBOT_SIZES[size];
  return (
    <Avatar size={avatarSize.quill} className={cn("shrink-0", className)}>
      <AvatarFallback>
        <Robot size={avatarSize.icon} />
      </AvatarFallback>
    </Avatar>
  );
}

export function AvatarStack({
  users,
  max = 4,
}: {
  users: McpGatewayUser[];
  max?: number;
}) {
  const shown = users.slice(0, max);
  const extra = users.length - shown.length;
  return (
    <AvatarGroup stacked size="xs">
      {shown.map((user) => (
        <UserAvatar
          key={user.uuid || user.email}
          user={user}
          size="xs"
          title={gatewayUserName(user)}
        />
      ))}
      {extra > 0 && (
        <Avatar size="xs">
          <AvatarFallback className="font-medium text-[9px]">
            +{extra}
          </AvatarFallback>
        </Avatar>
      )}
    </AvatarGroup>
  );
}
