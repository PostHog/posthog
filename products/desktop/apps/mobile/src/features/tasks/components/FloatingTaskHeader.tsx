import { Text } from "@components/text";
import { useRouter } from "expo-router";
import { CaretLeft } from "phosphor-react-native";
import type { ReactNode } from "react";
import { Platform, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useThemeColors } from "@/lib/theme";

interface FloatingTaskHeaderProps {
  title: string;
  subtitle?: string | null;
  /** Optional right-side action (e.g. a Local-run indicator). */
  rightSlot?: ReactNode;
}

/** Task detail toolbar with navigation, task identity, and run actions. */
export function FloatingTaskHeader({
  title,
  subtitle,
  rightSlot,
}: FloatingTaskHeaderProps) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const themeColors = useThemeColors();

  const handleBack = () => {
    if (router.canGoBack()) router.back();
  };

  // iOS modals already provide their own top chrome (drag handle / rounded
  // corners), so insets.top over-counts the space. Use a minimal fixed value
  // on iOS and fall back to the real inset on Android.
  const topInset = Platform.OS === "ios" ? 6 : insets.top;

  const headerHeight = topInset + 52;

  return (
    <View
      pointerEvents="box-none"
      className="absolute inset-x-0 top-0 z-10 border-gray-4 border-b bg-background"
      style={{ height: headerHeight }}
    >
      <View
        className="flex-row items-center px-3"
        style={{ paddingTop: topInset, paddingBottom: 4 }}
      >
        <Pressable
          onPress={handleBack}
          hitSlop={10}
          className="h-11 w-11 items-center justify-center active:opacity-60"
        >
          <CaretLeft size={22} color={themeColors.gray[12]} weight="bold" />
        </Pressable>

        <View className="min-w-0 flex-1 items-start px-2">
          <Text
            className="font-semibold text-[15px] text-gray-12"
            numberOfLines={1}
          >
            {title}
          </Text>
          {subtitle ? (
            <Text className="mt-0.5 text-[12px] text-gray-10" numberOfLines={1}>
              {subtitle}
            </Text>
          ) : null}
        </View>

        <View
          className="h-11 flex-row items-center justify-end gap-2"
          style={{ minWidth: 44 }}
        >
          {rightSlot}
        </View>
      </View>
    </View>
  );
}
