import { Text } from "@components/text";
import { CaretDown } from "phosphor-react-native";
import type { ReactNode } from "react";
import { Pressable, View } from "react-native";
import { useThemeColors } from "@/lib/theme";

interface PillProps {
  icon?: ReactNode;
  label: string;
  /** Optional secondary muted label, e.g. placeholder text "Select…". */
  placeholder?: boolean;
  /** Tone the label in accent (used for Plan Mode in the desktop). */
  accent?: boolean;
  onPress: () => void;
}

export function Pill({ icon, label, placeholder, accent, onPress }: PillProps) {
  const themeColors = useThemeColors();
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center gap-1.5 rounded-md border border-gray-6 bg-card px-2.5 py-1.5 active:bg-gray-3"
    >
      {icon ? <View className="shrink-0">{icon}</View> : null}
      <Text
        className={`shrink text-[13px] ${
          placeholder
            ? "text-gray-10"
            : accent
              ? "font-medium text-accent-11"
              : "text-gray-12"
        }`}
        numberOfLines={1}
      >
        {label}
      </Text>
      <CaretDown size={12} color={themeColors.gray[10]} />
    </Pressable>
  );
}
