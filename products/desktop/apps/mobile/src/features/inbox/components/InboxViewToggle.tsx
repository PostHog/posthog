import * as Haptics from "expo-haptics";
import { Archive, Cards, type Icon, ListBullets } from "phosphor-react-native";
import { Pressable, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useThemeColors } from "@/lib/theme";

export type InboxViewMode = "list" | "tinder" | "archive";

const VIEW_MODES: { mode: InboxViewMode; icon: Icon; label: string }[] = [
  { mode: "list", icon: ListBullets, label: "List view" },
  { mode: "tinder", icon: Cards, label: "Card view" },
  { mode: "archive", icon: Archive, label: "Archive" },
];

interface InboxViewToggleProps {
  mode: InboxViewMode;
  onModeChange: (mode: InboxViewMode) => void;
}

/**
 * Floating pill toggle at the bottom of the inbox screen, with the active
 * segment highlighted.
 */
export function InboxViewToggle({ mode, onModeChange }: InboxViewToggleProps) {
  const insets = useSafeAreaInsets();
  const themeColors = useThemeColors();

  const handlePress = (next: InboxViewMode) => {
    if (next === mode) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    onModeChange(next);
  };

  return (
    <View
      className="absolute inset-x-0 items-center"
      style={{ bottom: insets.bottom + 16 }}
      pointerEvents="box-none"
    >
      <View className="elevation-4 flex-row items-center overflow-hidden rounded-full border border-gray-6 bg-card shadow-lg">
        {VIEW_MODES.map(({ mode: m, icon: IconCmp, label }) => {
          const active = mode === m;
          return (
            <Pressable
              key={m}
              onPress={() => handlePress(m)}
              hitSlop={4}
              accessibilityLabel={label}
              accessibilityRole="button"
              className={`items-center justify-center rounded-full px-5 py-3 ${active ? "bg-accent-9" : "active:bg-gray-3"}`}
            >
              <IconCmp
                size={20}
                weight={active ? "bold" : "regular"}
                color={
                  active ? themeColors.accent.contrast : themeColors.gray[11]
                }
              />
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}
