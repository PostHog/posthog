import { formatRelativeAge } from "@posthog/shared";
import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { colors } from "@/lib/theme";

const STATUS_LABELS: Record<TaskRunStatus, string> = {
  not_started: "Not started",
  queued: "Queued",
  in_progress: "Running",
  completed: "Done",
  failed: "Failed",
  cancelled: "Canceled",
};

function taskTime(task: Task): string {
  const run = task.latest_run;
  if (
    run?.completed_at &&
    ["completed", "failed", "cancelled"].includes(run.status)
  ) {
    const label = run.status === "completed" ? "Finished" : "Ended";
    return `${label} ${formatRelativeAge(run.completed_at)}`;
  }
  if (run?.status === "queued")
    return `Added ${formatRelativeAge(run.created_at)}`;
  if (run?.status === "in_progress" && task.last_activity_at)
    return `Active ${formatRelativeAge(task.last_activity_at)}`;
  return `Updated ${formatRelativeAge(task.updated_at)}`;
}

export function TaskListRow({
  task,
  onPress,
  preview = false,
  unread = false,
}: {
  task: Task;
  onPress: () => void;
  preview?: boolean;
  unread?: boolean;
}) {
  const status = task.latest_run?.status ?? "not_started";
  const failed = status === "failed";
  const title =
    task.title ||
    task.description_preview ||
    task.description ||
    "Untitled task";
  const time = taskTime(task);
  const statusLabel = STATUS_LABELS[status];
  const symbol =
    status === "failed"
      ? "!"
      : status === "completed"
        ? "✓"
        : status === "cancelled"
          ? "−"
          : status === "queued"
            ? "◷"
            : "";
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${unread ? "Unread. " : ""}${title}. ${statusLabel}. ${time}.`}
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.5 }]}
    >
      <View
        style={[styles.status, unread && styles.unread]}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
      >
        {symbol ? (
          <Text
            style={[
              styles.statusSymbol,
              failed && styles.failed,
              unread && { color: colors.unreadInk },
            ]}
          >
            {symbol}
          </Text>
        ) : (
          <View
            style={[styles.ring, status === "in_progress" && styles.running]}
          />
        )}
      </View>
      <View style={styles.body}>
        <Text
          style={[styles.title, unread && { fontWeight: "600" }]}
          numberOfLines={2}
        >
          {title}
        </Text>
        <Text style={styles.meta}>
          <Text style={failed && styles.failed}>{statusLabel}</Text> · {time}
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
    gap: 12,
    minHeight: 64,
    paddingVertical: 12,
    paddingHorizontal: 4,
  },
  status: {
    width: 26,
    height: 26,
    borderRadius: 7,
    backgroundColor: colors.fill,
    alignItems: "center",
    justifyContent: "center",
  },
  unread: { backgroundColor: colors.unread },
  ring: {
    width: 12,
    height: 12,
    borderRadius: 6,
    borderWidth: 1.5,
    borderColor: colors.inkMute,
  },
  running: {
    borderWidth: 2,
    borderColor: colors.inkSoft,
    borderRightColor: "transparent",
  },
  statusSymbol: {
    fontSize: 16,
    lineHeight: 21,
    fontWeight: "600",
    color: colors.inkSoft,
  },
  failed: { color: colors.dangerText, fontWeight: "600" },
  body: { flex: 1, gap: 3 },
  title: {
    fontWeight: "500",
    fontSize: 15,
    lineHeight: 21,
    color: colors.ink,
  },
  meta: { fontSize: 12, lineHeight: 18, color: colors.inkSoft },
  preview: {
    fontSize: 14,
    lineHeight: 20,
    color: colors.inkSoft,
  },
});
