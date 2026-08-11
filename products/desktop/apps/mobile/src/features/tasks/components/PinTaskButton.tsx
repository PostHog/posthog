import * as Haptics from "expo-haptics";
import { PushPin } from "phosphor-react-native";
import { Pressable } from "react-native";
import { useThemeColors } from "@/lib/theme";
import { usePinnedTasks } from "../hooks/usePinnedTasks";

interface PinTaskButtonProps {
  taskId: string;
}

/** Pin/unpin toggle for the task detail header. Pins are per-user and
 *  server-synced, shared with desktop's pinned sidebar section. */
export function PinTaskButton({ taskId }: PinTaskButtonProps) {
  const themeColors = useThemeColors();
  const { isPinned, togglePin } = usePinnedTasks();
  const pinned = isPinned(taskId);

  return (
    <Pressable
      onPress={() => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        togglePin(taskId);
      }}
      hitSlop={8}
      accessibilityLabel={pinned ? "Unpin task" : "Pin task"}
      className="h-8 w-8 items-center justify-center rounded-lg active:bg-gray-3"
    >
      <PushPin
        size={18}
        color={pinned ? themeColors.accent[9] : themeColors.gray[11]}
        weight={pinned ? "fill" : "regular"}
      />
    </Pressable>
  );
}
