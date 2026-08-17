import { Plus } from "phosphor-react-native";
import { Pressable } from "react-native";
import { Text } from "@/components/text";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";

interface FloatingNewAutomationButtonProps {
  onPress: () => void;
}

/**
 * Pill-shaped FAB anchored to the bottom-right corner — mirrors
 * FloatingNewTaskButton so the two tabs feel like siblings.
 */
export function FloatingNewAutomationButton({
  onPress,
}: FloatingNewAutomationButtonProps) {
  const { fabBottom } = useScreenInsets();
  const themeColors = useThemeColors();

  return (
    <Pressable
      onPress={onPress}
      hitSlop={8}
      accessibilityLabel="Create new automation"
      accessibilityRole="button"
      className="absolute right-5 z-10 h-14 flex-row items-center justify-center gap-2 rounded-full bg-accent-9 pr-5 pl-4 active:opacity-85"
      style={{
        bottom: fabBottom(),
        shadowColor: "#000",
        shadowOpacity: 0.22,
        shadowRadius: 12,
        shadowOffset: { width: 0, height: 4 },
        elevation: 6,
      }}
    >
      <Plus size={22} color={themeColors.accent.contrast} weight="bold" />
      <Text className="font-semibold text-[15px] text-accent-contrast leading-tight">
        New automation
      </Text>
    </Pressable>
  );
}
