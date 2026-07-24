import { Text } from "@components/text";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { CaretLeft } from "phosphor-react-native";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { toRgba, useThemeColors } from "@/lib/theme";

/**
 * Floating header for the settings screen — back arrow on the left and a
 * centered "Settings" title. Sits over the content with a top-to-bottom fade
 * so the scrolled list disappears gracefully behind it.
 */
export function FloatingSettingsHeader() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const themeColors = useThemeColors();

  const handleBack = () => {
    if (router.canGoBack()) {
      router.back();
      return;
    }
    router.replace("/tasks");
  };

  const fadeHeight = insets.top + 88;

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
          toRgba(themeColors.background, 0.92),
          toRgba(themeColors.background, 0),
        ]}
        locations={[0, 0.65, 1]}
        style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
      />

      <View
        className="flex-row items-center px-3"
        style={{ paddingTop: insets.top + 6, paddingBottom: 8 }}
      >
        <Pressable
          onPress={handleBack}
          hitSlop={10}
          className="h-11 w-11 items-center justify-center active:opacity-60"
          accessibilityLabel="Back"
          accessibilityRole="button"
        >
          <CaretLeft size={22} color={themeColors.gray[12]} weight="bold" />
        </Pressable>

        <View className="min-w-0 flex-1 items-center px-2">
          <Text
            className="font-semibold text-[17px] text-gray-12"
            numberOfLines={1}
          >
            Settings
          </Text>
        </View>

        {/* Right spacer to keep the title visually centered against the back button. */}
        <View className="h-11 w-11" />
      </View>
    </View>
  );
}
