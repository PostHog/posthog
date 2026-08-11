import { Text } from "@components/text";
import { CloudArrowUp } from "phosphor-react-native";
import { ActivityIndicator, Pressable, View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import type { LocalRunState } from "../utils/taskRunPlacement";

interface ContinueInCloudBarProps {
  state: LocalRunState;
  /** A cloud run is being started right now. */
  starting?: boolean;
  onContinueInCloud: () => void;
}

/**
 * Stands in for the composer on a desktop-owned task. Mobile can't attach to a
 * desktop session, so a text box would only ever produce a failed send — this
 * offers the one thing that does work instead, and stays disabled until the
 * desktop run has finished so the two can't race.
 *
 * Matches the composer's own width constraints so the bottom of the screen
 * doesn't shift when a task turns out to be desktop-local.
 */
export function ContinueInCloudBar({
  state,
  starting = false,
  onContinueInCloud,
}: ContinueInCloudBarProps) {
  const themeColors = useThemeColors();
  const disabled = !state.canContinue || starting;

  return (
    <View className="px-4">
      <View style={{ width: "100%", maxWidth: 600, alignSelf: "center" }}>
        <Pressable
          onPress={onContinueInCloud}
          disabled={disabled}
          accessibilityRole="button"
          accessibilityState={{ disabled }}
          accessibilityLabel={state.actionLabel}
          className={`w-full flex-row items-center justify-center gap-2 rounded-lg px-4 py-3.5 ${
            disabled ? "bg-gray-3" : "active:opacity-80"
          }`}
          style={disabled ? null : { backgroundColor: themeColors.accent[9] }}
        >
          {starting ? (
            <ActivityIndicator size="small" color={themeColors.gray[11]} />
          ) : (
            <CloudArrowUp
              size={18}
              weight="bold"
              color={
                disabled ? themeColors.gray[10] : themeColors.accent.contrast
              }
            />
          )}
          <Text
            className={`font-semibold text-[15px] ${
              disabled ? "text-gray-10" : "text-accent-contrast"
            }`}
          >
            {state.actionLabel}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}
