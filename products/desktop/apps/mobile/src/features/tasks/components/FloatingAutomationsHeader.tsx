import { Text } from "@components/text";
import { LinearGradient } from "expo-linear-gradient";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { MenuButton } from "@/features/navigation/components/MenuButton";
import { toRgba, useThemeColors } from "@/lib/theme";

/**
 * Floating header for the Automations list — mirrors FloatingTasksHeader so
 * the two tabs feel like siblings. Hamburger on the left, centered title,
 * gradient fade so the list content disappears gracefully behind it.
 */
export function FloatingAutomationsHeader() {
  const insets = useSafeAreaInsets();
  const themeColors = useThemeColors();

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
        <MenuButton />

        <View className="min-w-0 flex-1 items-center px-2">
          <Text
            className="font-semibold text-[17px] text-gray-12"
            numberOfLines={1}
          >
            Automations
          </Text>
        </View>

        {/* Spacer mirroring the MenuButton width so the title stays
            optically centered. */}
        <View className="h-10 w-10" />
      </View>
    </View>
  );
}
