import { formatRelativeAge } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { Dot } from "@/components/Icons";
import { colors, fonts } from "@/lib/theme";

export function TaskListRow({
  task,
  onPress,
  preview = false,
}: {
  task: Task;
  onPress: () => void;
  preview?: boolean;
}) {
  const status = task.latest_run?.status;
  const live =
    status === "queued" || status === "not_started" || status === "in_progress";
  const failed = status === "failed";
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.5 }]}
    >
      <View style={styles.dot}>
        <Dot
          color={failed ? colors.danger : live ? colors.accent : colors.inkMute}
          hollow={!live && !failed}
        />
      </View>
      <View style={styles.body}>
        <Text style={styles.title} numberOfLines={2}>
          {task.title ||
            task.description_preview ||
            task.description ||
            "Untitled task"}
        </Text>
        <Text style={styles.meta} numberOfLines={1}>
          {formatRelativeAge(task.last_activity_at || task.updated_at)}
        </Text>
        {preview && task.description_preview ? (
          <Text style={styles.preview} numberOfLines={2}>
            {task.description_preview}
          </Text>
        ) : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 4,
  },
  dot: { paddingTop: 6 },
  body: { flex: 1, gap: 4 },
  title: {
    fontFamily: fonts.sansMedium,
    fontSize: 14,
    lineHeight: 19,
    color: colors.ink,
  },
  meta: { fontFamily: fonts.sans, fontSize: 12, color: colors.inkMute },
  preview: {
    fontFamily: fonts.sans,
    fontSize: 14,
    lineHeight: 20,
    color: colors.inkSoft,
  },
});
