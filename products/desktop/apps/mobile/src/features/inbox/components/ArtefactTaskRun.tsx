import { Text } from "@components/text";
import { useRouter } from "expo-router";
import { CaretRight } from "phosphor-react-native";
import { Pressable, View } from "react-native";
import { useTask } from "@/features/tasks";
import { useThemeColors } from "@/lib/theme";
import { taskRunLabel } from "../activityLog";
import type { TaskRunArtefactContent } from "../types";

export function ArtefactTaskRun({
  content,
}: {
  content: TaskRunArtefactContent;
}) {
  const router = useRouter();
  const themeColors = useThemeColors();
  const taskQuery = useTask(content.task_id);

  const task = taskQuery.data;
  const label = taskRunLabel(content);
  const status = task?.latest_run?.status;

  return (
    <Pressable
      onPress={() => router.push(`/task/${content.task_id}`)}
      hitSlop={4}
      accessibilityRole="button"
      className="flex-row items-center gap-2 py-1 active:opacity-60"
    >
      <View className="rounded bg-gray-4 px-1.5 py-0.5">
        <Text className="font-medium text-[11px] text-gray-11">{label}</Text>
      </View>
      <Text
        className="min-w-0 flex-1 text-[13px] text-gray-12"
        numberOfLines={1}
      >
        {taskQuery.isLoading
          ? "Loading task…"
          : (task?.title ?? content.task_id)}
      </Text>
      {status ? (
        <View className="rounded bg-gray-4 px-1.5 py-0.5">
          <Text className="text-[11px] text-gray-11">{status}</Text>
        </View>
      ) : null}
      <CaretRight size={14} color={themeColors.gray[9]} />
    </Pressable>
  );
}
