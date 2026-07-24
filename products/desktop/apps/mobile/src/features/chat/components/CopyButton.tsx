import * as Haptics from "expo-haptics";
import { Check, Copy } from "phosphor-react-native";
import { useCallback } from "react";
import { Pressable } from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useCopy } from "../hooks/useCopy";

interface CopyButtonProps {
  text: string;
  size?: number;
  label?: string;
}

export function CopyButton({ text, size = 14, label }: CopyButtonProps) {
  const themeColors = useThemeColors();
  const { copied, copy } = useCopy();

  const handlePress = useCallback(() => {
    copy(text, () => Haptics.selectionAsync());
  }, [copy, text]);

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={8}
      accessibilityRole="button"
      accessibilityLabel={label ?? "Copy"}
    >
      {copied ? (
        <Check size={size} color={themeColors.status.success} />
      ) : (
        <Copy size={size} color={themeColors.gray[9]} />
      )}
    </Pressable>
  );
}
