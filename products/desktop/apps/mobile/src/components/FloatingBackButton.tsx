import { useRouter } from "expo-router";
import { CaretLeft } from "phosphor-react-native";
import { Pressable } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useThemeColors } from "@/lib/theme";

interface FloatingBackButtonProps {
  /** Override the default `router.back()` action. */
  onPress?: () => void;
}

/**
 * Pill-shaped back button that floats over the top-left of a screen. Used in
 * place of a native stack header so the content can fill the full screen
 * (e.g. behind a dotted background).
 */
export function FloatingBackButton({ onPress }: FloatingBackButtonProps) {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const themeColors = useThemeColors();

  const handlePress = () => {
    if (onPress) {
      onPress();
      return;
    }
    if (router.canGoBack()) {
      router.back();
    }
  };

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={8}
      className="absolute left-3 z-10 h-11 w-11 items-center justify-center rounded-full border border-gray-6 bg-card active:bg-gray-3"
      style={{ top: insets.top + 8 }}
    >
      <CaretLeft size={22} color={themeColors.gray[12]} weight="bold" />
    </Pressable>
  );
}
