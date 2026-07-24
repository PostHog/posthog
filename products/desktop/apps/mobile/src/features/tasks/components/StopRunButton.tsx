import { Text } from "@components/text";
import { Stop } from "phosphor-react-native";
import { Pressable } from "react-native";
import { useThemeColors } from "@/lib/theme";

interface StopRunButtonProps {
  onPress: () => void;
}

export function StopRunButton({ onPress }: StopRunButtonProps) {
  const themeColors = useThemeColors();
  return (
    <Pressable
      onPress={onPress}
      hitSlop={8}
      className="h-8 flex-row items-center gap-1 rounded-full border border-status-error/40 bg-status-error/10 px-2.5 active:opacity-60"
    >
      <Stop size={14} color={themeColors.status.error} weight="fill" />
      <Text className="font-medium text-[13px] text-status-error">Stop</Text>
    </Pressable>
  );
}
