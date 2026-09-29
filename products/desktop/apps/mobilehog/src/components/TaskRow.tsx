import { Button, ContextMenu, Host, RNHostView } from "@expo/ui/swift-ui";
import { formatRelativeAge } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useEffect } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import { useUpdateTask } from "@/lib/queries";
import { colors, fonts } from "@/lib/theme";

function isRunning(task: Task): boolean {
  const status = task.latest_run?.status;
  return status === "queued" || status === "in_progress";
}

export function activityAt(task: Task): string {
  return task.last_activity_at ?? task.updated_at;
}

function taskTitle(task: Task): string {
  return (
    task.title || task.description_preview || task.description || "Untitled"
  );
}

export function ListRow({
  title,
  label,
  time,
  running = false,
  onPress,
}: {
  title: string;
  label?: string;
  time: string;
  running?: boolean;
  onPress: () => void;
}) {
  const age = formatRelativeAge(time);
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.5 }]}
    >
      <View style={styles.body}>
        <Text style={styles.title} numberOfLines={2}>
          {title}
        </Text>
        <Text style={styles.time}>{label ? `${label} · ${age}` : age}</Text>
      </View>
      {running ? (
        <ActivityIndicator size="small" color={colors.inkSoft} />
      ) : null}
    </Pressable>
  );
}

export function TaskRow({
  task,
  label,
  onPress,
}: {
  task: Task;
  label?: string;
  onPress: () => void;
}) {
  const updateTask = useUpdateTask();
  const rename = (): void =>
    Alert.prompt(
      "Rename",
      "Enter a new name",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "OK",
          onPress: (title?: string) => {
            if (title?.trim()) {
              updateTask.mutate({ id: task.id, title: title.trim() });
            }
          },
        },
      ],
      "plain-text",
      taskTitle(task),
    );
  return (
    <Host matchContents={{ vertical: true }}>
      <ContextMenu>
        <ContextMenu.Items>
          <Button label="Rename" systemImage="pencil" onPress={rename} />
          <Button
            label="Archive"
            systemImage="archivebox"
            onPress={() => updateTask.mutate({ id: task.id, archived: true })}
          />
        </ContextMenu.Items>
        <ContextMenu.Trigger>
          <RNHostView matchContents>
            <ListRow
              title={taskTitle(task)}
              label={label}
              time={activityAt(task)}
              running={isRunning(task)}
              onPress={onPress}
            />
          </RNHostView>
        </ContextMenu.Trigger>
      </ContextMenu>
    </Host>
  );
}

const SKELETON_WIDTHS = ["72%", "54%", "86%", "62%", "78%"] as const;

export function RowSkeletons() {
  const opacity = useSharedValue(1);
  useEffect(() => {
    opacity.value = withRepeat(
      withTiming(0.4, { duration: 800, easing: Easing.inOut(Easing.ease) }),
      -1,
      true,
    );
  }, [opacity]);
  const pulse = useAnimatedStyle(() => ({ opacity: opacity.value }));
  return (
    <Animated.View style={pulse}>
      {SKELETON_WIDTHS.map((width) => (
        <View key={width} style={styles.row}>
          <View style={styles.body}>
            <View style={[styles.skeletonTitle, { width }]} />
            <View style={styles.skeletonTime} />
          </View>
        </View>
      ))}
    </Animated.View>
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
  title: {
    fontFamily: fonts.sansMedium,
    fontSize: 17,
    lineHeight: 23,
    color: colors.ink,
  },
  time: { fontFamily: fonts.sans, fontSize: 14, color: colors.inkSoft },
  skeletonTitle: {
    height: 17,
    marginVertical: 3,
    borderRadius: 6,
    backgroundColor: colors.fill,
  },
  skeletonTime: {
    width: 56,
    height: 14,
    marginVertical: 2,
    borderRadius: 5,
    backgroundColor: colors.fill,
  },
});
