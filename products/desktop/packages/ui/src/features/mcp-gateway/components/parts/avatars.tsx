import { Robot } from "@phosphor-icons/react";
import type { McpGatewayUser } from "@posthog/api-client/posthog-client";
import { Avatar, Flex } from "@radix-ui/themes";

export function gatewayUserName(user: McpGatewayUser): string {
  const name = [user.first_name, user.last_name]
    .filter(Boolean)
    .join(" ")
    .trim();
  return name || user.email;
}

function initialsOf(user: McpGatewayUser): string {
  const parts = [user.first_name, user.last_name].filter(
    (part): part is string => !!part,
  );
  if (parts.length) {
    return parts
      .map((part) => part[0])
      .join("")
      .slice(0, 2)
      .toUpperCase();
  }
  return user.email.slice(0, 2).toUpperCase();
}

const USER_AVATAR_COLORS = [
  "amber",
  "blue",
  "cyan",
  "green",
  "indigo",
  "orange",
  "pink",
  "purple",
  "teal",
] as const;

// Keep a stable color for each member while staying inside the Radix theme
// palette rather than synthesizing colors outside the design system.
function avatarColorOf(
  user: McpGatewayUser,
): (typeof USER_AVATAR_COLORS)[number] {
  const seed = user.uuid || user.email;
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) | 0;
  }
  return (
    USER_AVATAR_COLORS[(hash >>> 0) % USER_AVATAR_COLORS.length] ?? "amber"
  );
}

const AVATAR_SIZES = {
  sm: { radix: "1", pixels: 20 },
  md: { radix: "2", pixels: 26 },
  lg: { radix: "3", pixels: 40 },
} as const;

export function UserAvatar({
  user,
  size = "md",
  className,
}: {
  user: McpGatewayUser;
  size?: keyof typeof AVATAR_SIZES;
  className?: string;
}) {
  const avatarSize = AVATAR_SIZES[size];
  return (
    <Avatar
      fallback={initialsOf(user)}
      color={avatarColorOf(user)}
      radius="full"
      size={avatarSize.radix}
      title={gatewayUserName(user)}
      className={`shrink-0 font-semibold ${className ?? ""}`}
      style={{
        width: avatarSize.pixels,
        height: avatarSize.pixels,
        fontSize: Math.round(avatarSize.pixels * 0.38),
      }}
    />
  );
}

export function RobotAvatar({
  size = "md",
  className,
}: {
  size?: keyof typeof AVATAR_SIZES;
  className?: string;
}) {
  const avatarSize = AVATAR_SIZES[size];
  return (
    <Avatar
      fallback={<Robot size={Math.round(avatarSize.pixels * 0.62)} />}
      color="gray"
      radius="medium"
      size={avatarSize.radix}
      className={`shrink-0 ${className ?? ""}`}
      style={{ width: avatarSize.pixels, height: avatarSize.pixels }}
    />
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
    <Flex align="center" className="-space-x-1">
      {shown.map((user) => (
        <UserAvatar
          key={user.uuid || user.email}
          user={user}
          size="sm"
          className="ring-(--gray-1) ring-1"
        />
      ))}
      {extra > 0 && (
        <Flex
          align="center"
          justify="center"
          className="h-[20px] w-[20px] shrink-0 rounded-full bg-gray-4 font-medium text-[9px] text-gray-11 ring-(--gray-1) ring-1"
        >
          +{extra}
        </Flex>
      )}
    </Flex>
  );
}
