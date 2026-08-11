import { Text } from "@components/text";
import { Laptop } from "phosphor-react-native";
import { View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import type { LocalRunState } from "../utils/taskRunPlacement";

interface LocalRunBannerProps {
  state: LocalRunState;
}

/**
 * One-line notice on a task whose latest run happened on the user's desktop.
 * Purely informational: the action lives in `ContinueInCloudBar`, which has
 * taken the composer's place at the bottom of the screen.
 */
export function LocalRunBanner({ state }: LocalRunBannerProps) {
  const themeColors = useThemeColors();

  return (
    <View className="flex-row items-center gap-2 rounded-lg border border-gray-6 bg-gray-2 px-3 py-2">
      <Laptop size={14} weight="bold" color={themeColors.gray[11]} />
      <Text className="flex-1 text-[12px] text-gray-11" numberOfLines={1}>
        {state.notice}
      </Text>
    </View>
  );
}
