import { formatRelativeAge } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { colors } from "@/lib/theme";

export function TaskListRow({
  task,
  onPress,
  preview = false,
}: {
  task: Task;
  onPress: () => void;
  preview?: boolean;
}) {
  const running =
    task.latest_run?.status === "in_progress" ||
    task.latest_run?.status === "queued";
  const title =
    task.title ||
    task.description_preview ||
    task.description ||
    "Untitled task";
  const time = formatRelativeAge(task.last_activity_at ?? task.updated_at);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${title}.${running ? " Running." : ""} Updated ${time}.`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.5 }]}
    >
      <View style={styles.body}>
        <Text style={styles.title} numberOfLines={2}>
          {title}
        </Text>
        <Text style={styles.meta}>{time}</Text>
        {preview && task.description_preview ? (
          <Text style={styles.preview} numberOfLines={2}>
            {task.description_preview}
          </Text>
        ) : null}
      </View>
      {running ? (
        <ActivityIndicator
          size="small"
          color={colors.inkSoft}
          accessibilityLabel="Running"
        />
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minHeight: 64,
    paddingVertical: 12,
    paddingHorizontal: 4,
  },
  body: { flex: 1, minWidth: 0, gap: 3 },
  title: { fontWeight: "500", fontSize: 15, lineHeight: 21, color: colors.ink },
  meta: { fontSize: 12, lineHeight: 18, color: colors.inkSoft },
  preview: { fontSize: 14, lineHeight: 20, color: colors.inkSoft },
});
