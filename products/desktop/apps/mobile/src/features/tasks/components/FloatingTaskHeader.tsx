import { Text } from "@components/text";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { CaretLeft } from "phosphor-react-native";
import type { ReactNode } from "react";
import { Platform, Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { toRgba, useThemeColors } from "@/lib/theme";

interface FloatingTaskHeaderProps {
  title: string;
  subtitle?: string | null;
  /** Optional right-side action (e.g. a Local-run indicator). */
  rightSlot?: ReactNode;
}

/**
 * Floating header for the task detail screen — back arrow on the left,
 * centered title + repo subtitle, optional right slot for actions. Sits over
 * the content with a top-to-bottom fade so the scroll list disappears
 * gracefully behind it rather than getting clipped by a hard edge.
 */
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

  // Fade height extends well past the title row so content scrolling up
  // behind the header gets a long, gentle transition instead of crashing
  // into the subtitle. Header row content sits in roughly the first
  // (topInset + 44)pt; the rest is pure fade.
  const fadeHeight = topInset + 96;

  return (
    <View
      pointerEvents="box-none"
      className="absolute inset-x-0 top-0 z-10"
      style={{ height: fadeHeight }}
    >
      <LinearGradient
        pointerEvents="none"
        colors={[
          toRgba(themeColors.background, 1),
          toRgba(themeColors.background, 1),
          toRgba(themeColors.background, 0.85),
          toRgba(themeColors.background, 0),
        ]}
        locations={[0, 0.5, 0.75, 1]}
        style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
      />

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

        <View className="min-w-0 flex-1 items-center px-2">
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
