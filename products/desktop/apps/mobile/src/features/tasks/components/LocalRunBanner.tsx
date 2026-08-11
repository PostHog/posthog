import { Text } from "@components/text";
import { Laptop } from "phosphor-react-native";
import { ActivityIndicator, Pressable, View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import {
  getLocalRunBannerState,
  type TaskRunPlacement,
} from "../utils/taskRunPlacement";

interface LocalRunBannerProps {
  placement: TaskRunPlacement;
  /** A cloud run is being started right now. */
  starting?: boolean;
  onContinueInCloud: () => void;
}

/**
 * Shown on a task whose latest run happened on the user's desktop. Mobile
 * can't attach to a desktop session, so the only move is to start a fresh
 * cloud run from it — and only once the desktop run has actually finished,
 * so the two never race.
 */
export function LocalRunBanner({
  placement,
  starting = false,
  onContinueInCloud,
}: LocalRunBannerProps) {
  const themeColors = useThemeColors();
  const state = getLocalRunBannerState(placement);
  if (!state) return null;

  const disabled = !state.canContinue || starting;

  return (
    <View className="flex-row items-center gap-3 rounded-lg border border-gray-6 bg-gray-2 px-3 py-2.5">
      <Laptop size={16} weight="bold" color={themeColors.gray[11]} />
      <Text className="flex-1 text-[12px] text-gray-11" numberOfLines={2}>
        {state.message}
      </Text>
      <Pressable
        onPress={onContinueInCloud}
        disabled={disabled}
        accessibilityRole="button"
        accessibilityState={{ disabled }}
        accessibilityLabel={state.actionLabel}
        className={`shrink-0 flex-row items-center gap-1.5 rounded-full px-3 py-1.5 ${disabled ? "bg-gray-4" : "active:opacity-80"}`}
        style={disabled ? null : { backgroundColor: themeColors.accent[9] }}
      >
        {starting ? (
          <ActivityIndicator size="small" color={themeColors.gray[11]} />
        ) : null}
        <Text
          className={`font-semibold text-[12px] ${disabled ? "text-gray-10" : "text-accent-contrast"}`}
        >
          {state.actionLabel}
        </Text>
      </Pressable>
    </View>
  );
}
