import { Text } from "@components/text";
import * as Haptics from "expo-haptics";
import { PushPin } from "phosphor-react-native";
import { useMemo } from "react";
import { Pressable, ScrollView, View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useAwaitingInputTaskIds } from "../hooks/useAwaitingInputTasks";
import { usePinnedTasks } from "../hooks/usePinnedTasks";
import { useTasks } from "../hooks/useTasks";
import { TaskStatusIcon } from "./TaskStatusIcon";

interface PinnedTasksRailProps {
  onTaskPress: (taskId: string) => void;
}

/**
 * Horizontal quick-switch rail over the user's pinned tasks — the mobile
 * shape of desktop's pinned sidebar section, backed by the same per-user
 * server-synced pins, so a task pinned on desktop shows up here too.
 * Newest pins first (server order). Tap opens the task; long-press unpins.
 */
export function PinnedTasksRail({ onTaskPress }: PinnedTasksRailProps) {
  const themeColors = useThemeColors();
  const { pinnedTaskIds, togglePin } = usePinnedTasks();
  const { allTasks } = useTasks();
  const awaitingInputTaskIds = useAwaitingInputTaskIds();

  const pinnedTasks = useMemo(() => {
    const byId = new Map(allTasks.map((task) => [task.id, task]));
    // Pins referencing tasks this list can't show (e.g. outside the fetch
    // window) are skipped rather than rendered as dead chips.
    return pinnedTaskIds.flatMap((id) => byId.get(id) ?? []);
  }, [pinnedTaskIds, allTasks]);

  if (pinnedTasks.length === 0) return null;

  return (
    <View className="pb-1">
      <View className="flex-row items-center gap-1.5 px-4 pb-1.5">
        <PushPin size={12} color={themeColors.gray[10]} weight="fill" />
        <Text
          className="font-medium text-[11px] text-gray-10 uppercase"
          style={{ letterSpacing: 0.5 }}
        >
          Pinned
        </Text>
      </View>
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: 12, gap: 8 }}
      >
        {pinnedTasks.map((task) => {
          const awaitingInput = awaitingInputTaskIds.has(task.id);
          return (
            <Pressable
              key={task.id}
              onPress={() => onTaskPress(task.id)}
              onLongPress={() => {
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
                togglePin(task.id);
              }}
              accessibilityLabel={`Open pinned task: ${task.title}`}
              accessibilityHint="Long press to unpin"
              className="flex-row items-center gap-2 rounded-full border border-gray-6 bg-gray-2 py-2 pr-3.5 pl-2.5 active:bg-gray-3"
              style={{ maxWidth: 220 }}
            >
              <TaskStatusIcon task={task} size={14} />
              <Text
                className={`text-[13px] text-gray-12 ${awaitingInput ? "font-bold" : ""}`}
                numberOfLines={1}
                ellipsizeMode="tail"
              >
                {task.title}
              </Text>
              {awaitingInput ? (
                <View
                  className="h-1.5 w-1.5 shrink-0 rounded-full"
                  style={{ backgroundColor: themeColors.accent[9] }}
                  accessibilityLabel="Waiting on you"
                />
              ) : null}
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}
