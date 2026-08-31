import { Text } from "@components/text";
import { avatarColor } from "@posthog/core/auth/avatarColor";
import {
  getUserInitials,
  type UserLike,
} from "@posthog/core/auth/userInitials";
import { ArrowSquareOut, ArrowsClockwise } from "phosphor-react-native";
import { Image, Pressable, View } from "react-native";
import {
  type ProfilePictureStatus,
  profilePictureDescription,
} from "@/features/auth/gravatar";
import { useThemeColors } from "@/lib/theme";

interface ProfilePictureRowProps {
  user: UserLike & { uuid?: string | null };
  imageUrl: string | undefined;
  status: ProfilePictureStatus;
  checking: boolean;
  onRefresh: () => void;
  onOpenGravatar: () => void;
}

export function ProfilePictureRow({
  user,
  imageUrl,
  status,
  checking,
  onRefresh,
  onOpenGravatar,
}: ProfilePictureRowProps) {
  const themeColors = useThemeColors();
  const email = user.email ?? "your email";
  const color = avatarColor(user.uuid ?? user.email ?? "user");
  const gravatarActionLabel =
    status === "found" ? "Change on Gravatar" : "Add on Gravatar";

  return (
    <View className="gap-3 border-gray-5 border-b px-4 py-3">
      <View className="flex-row items-center gap-3">
        <View
          className={`h-14 w-14 items-center justify-center overflow-hidden rounded-xl ${
            status === "missing" ? "border border-gray-7 border-dashed" : ""
          }`}
          style={{ backgroundColor: color.bg }}
        >
          <Text
            className="font-medium text-[18px]"
            style={{ color: color.text }}
          >
            {getUserInitials(user)}
          </Text>
          {imageUrl ? (
            <Image
              source={{ uri: imageUrl }}
              accessibilityIgnoresInvertColors
              className="absolute inset-0 h-full w-full"
            />
          ) : null}
        </View>

        <View className="min-w-0 flex-1">
          <Text className="font-medium text-[15px] text-gray-12">
            Profile picture
          </Text>
          <Text className="mt-0.5 text-[12px] text-gray-10 leading-snug">
            {profilePictureDescription(status, email)}
          </Text>
        </View>
      </View>

      <View className="flex-row gap-2">
        <Pressable
          onPress={onRefresh}
          disabled={checking}
          hitSlop={6}
          accessibilityLabel="Check Gravatar again"
          className={`flex-row items-center gap-1.5 rounded-md border border-gray-6 bg-gray-3 px-3 py-1.5 active:opacity-60 ${
            checking ? "opacity-50" : ""
          }`}
        >
          <ArrowsClockwise size={14} color={themeColors.gray[12]} />
          <Text className="font-medium text-[13px] text-gray-12">Refresh</Text>
        </Pressable>
        <Pressable
          onPress={onOpenGravatar}
          hitSlop={6}
          accessibilityLabel={`${gravatarActionLabel} (opens gravatar.com)`}
          className="flex-row items-center gap-1.5 rounded-md border border-gray-6 bg-gray-3 px-3 py-1.5 active:opacity-60"
        >
          <Text className="font-medium text-[13px] text-gray-12">
            {gravatarActionLabel}
          </Text>
          <ArrowSquareOut size={14} color={themeColors.gray[11]} />
        </Pressable>
      </View>
    </View>
  );
}
