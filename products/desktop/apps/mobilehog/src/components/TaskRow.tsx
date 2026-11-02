import {
  Button,
  ContextMenu,
  Host,
  Image,
  type ImageProps,
  RNHostView,
} from "@expo/ui/swift-ui";
import { formatRelativeAge } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { type ReactElement, useEffect } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
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

export function useTaskActions(task: Task | undefined) {
  const updateTask = useUpdateTask();
  const rename = (): void => {
    if (!task) return;
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
  };
  const setArchived = (archived: boolean, onSuccess?: () => void): void => {
    if (task) updateTask.mutate({ id: task.id, archived }, { onSuccess });
  };
  return { rename, setArchived };
}

function TaskMenu({
  task,
  archived,
  children,
}: {
  task: Task;
  archived: boolean;
  children: ReactElement;
}) {
  const { rename, setArchived } = useTaskActions(task);
  return (
    <Host matchContents={{ vertical: true }}>
      <ContextMenu>
        <ContextMenu.Items>
          <Button label="Rename" systemImage="pencil" onPress={rename} />
          {archived ? (
            <Button
              label="Restore"
              systemImage="arrow.uturn.backward"
              onPress={() => setArchived(false)}
            />
          ) : (
            <Button
              label="Archive"
              systemImage="archivebox"
              onPress={() => setArchived(true)}
            />
          )}
        </ContextMenu.Items>
        <ContextMenu.Trigger>
          <RNHostView matchContents>{children}</RNHostView>
        </ContextMenu.Trigger>
      </ContextMenu>
    </Host>
  );
}

export function TaskRow({
  task,
  label,
  archived = false,
  onPress,
}: {
  task: Task;
  label?: string;
  archived?: boolean;
  onPress: () => void;
}) {
  return (
    <TaskMenu task={task} archived={archived}>
      <ListRow
        title={taskTitle(task)}
        label={label}
        time={activityAt(task)}
        running={isRunning(task)}
        onPress={onPress}
      />
    </TaskMenu>
  );
}

function oneLine(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

// Titles made from the prompt repeat it, so the age stands in for the snippet.
function taskSnippet(task: Task, title: string): string {
  const snippet = oneLine(task.description_preview || task.description);
  return snippet && !snippet.startsWith(oneLine(title))
    ? snippet
    : formatRelativeAge(activityAt(task));
}

// A fixed height, so the SwiftUI host around a row never has to catch up with
// a title that wraps. Only the two text lines follow the text size setting.
function useChatRowHeight(): number {
  const { fontScale } = useWindowDimensions();
  return Math.ceil(21 + 39 * fontScale);
}

export function ChatRow({
  icon,
  title,
  snippet,
  running = false,
  onPress,
}: {
  icon: NonNullable<ImageProps["systemName"]>;
  title: string;
  snippet: string;
  running?: boolean;
  onPress: () => void;
}) {
  const height = useChatRowHeight();
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.chatRow,
        { height },
        pressed && { opacity: 0.5 },
      ]}
    >
      <View style={styles.chatIcon}>
        <Host matchContents>
          <Image systemName={icon} size={16} color={colors.inkSoft} />
        </Host>
      </View>
      <View style={styles.body}>
        <Text style={styles.chatTitle} numberOfLines={1}>
          {title}
        </Text>
        <Text style={styles.chatSnippet} numberOfLines={1}>
          {snippet}
        </Text>
      </View>
      {running ? (
        <ActivityIndicator size="small" color={colors.inkSoft} />
      ) : null}
    </Pressable>
  );
}

export function TaskChatRow({
  task,
  archived = false,
  onPress,
}: {
  task: Task;
  archived?: boolean;
  onPress: () => void;
}) {
  const title = taskTitle(task);
  return (
    <TaskMenu task={task} archived={archived}>
      <ChatRow
        icon="bubble.left"
        title={title}
        snippet={taskSnippet(task, title)}
        running={isRunning(task)}
        onPress={onPress}
      />
    </TaskMenu>
  );
}

const SKELETON_WIDTHS = ["72%", "54%", "86%", "62%", "78%"] as const;

export function RowSkeletons({
  count = SKELETON_WIDTHS.length,
  chat = false,
}: {
  count?: number;
  chat?: boolean;
}) {
  const chatHeight = useChatRowHeight();
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
      {SKELETON_WIDTHS.slice(0, count).map((width) => (
        <View
          key={width}
          style={chat ? [styles.chatRow, { height: chatHeight }] : styles.row}
        >
          {chat ? <View style={styles.chatIcon} /> : null}
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
  chatRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 4,
  },
  chatIcon: {
    width: 36,
    height: 36,
    borderRadius: 10,
    borderCurve: "continuous",
    backgroundColor: colors.fill,
    alignItems: "center",
    justifyContent: "center",
  },
  chatTitle: {
    fontFamily: fonts.sansMedium,
    fontSize: 16,
    lineHeight: 21,
    color: colors.ink,
  },
  chatSnippet: {
    fontFamily: fonts.sans,
    fontSize: 14,
    lineHeight: 18,
    color: colors.inkMute,
  },
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
