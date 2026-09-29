import { Button, ContextMenu, Host, RNHostView } from "@expo/ui/swift-ui";
import { formatRelativeAge } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useRouter } from "expo-router";
import { useMemo } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { DrawerEdgeShadow } from "@/components/DrawerEdgeShadow";
import { FadeScrim } from "@/components/FadeScrim";
import { GlassCircleButton } from "@/components/Glass";
import { BellIcon, SteeringIcon } from "@/components/Icons";
import { useActivity } from "@/lib/activity";
import { useAuth } from "@/lib/auth";
import { useTasks, useUpdateTask } from "@/lib/queries";
import { useReports, useSeenReports } from "@/lib/reports";
import { colors, fonts, radius } from "@/lib/theme";

function isRunning(task: Task): boolean {
  const status = task.latest_run?.status;
  return status === "queued" || status === "in_progress";
}

function activityAt(task: Task): string {
  return task.last_activity_at ?? task.updated_at;
}

function taskTitle(task: Task): string {
  return (
    task.title || task.description_preview || task.description || "Untitled"
  );
}

export function DrawerContent({ closeDrawer }: { closeDrawer: () => void }) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const tasks = useTasks();
  const userName = useAuth((s) => s.session?.userName ?? "");
  const unread = useActivity().data?.unread_count ?? 0;
  const reports = useReports().data ?? [];
  const seenReports = useSeenReports((s) => s.seen);
  const newReports = reports.filter(
    (report) => !seenReports.has(report.id),
  ).length;
  const sorted = useMemo(
    () =>
      [...(tasks.data ?? [])].sort((a, b) =>
        activityAt(b).localeCompare(activityAt(a)),
      ),
    [tasks.data],
  );

  const updateTask = useUpdateTask();
  const rename = (task: Task): void =>
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

  const open = (taskId: string): void => {
    closeDrawer();
    router.push({ pathname: "/(drawer)/task/[id]", params: { id: taskId } });
  };

  return (
    <View style={[styles.root, { paddingTop: insets.top + 18 }]}>
      <DrawerEdgeShadow />
      <Text style={styles.wordmark}>PostHog</Text>
      <ScrollView
        contentContainerStyle={[
          styles.scroll,
          { paddingBottom: FOOTER_HEIGHT + insets.bottom + 24 },
        ]}
        showsVerticalScrollIndicator={false}
      >
        <Pressable
          onPress={() => {
            closeDrawer();
            router.push("/(drawer)/activity");
          }}
          style={({ pressed }) => [styles.navRow, pressed && { opacity: 0.5 }]}
        >
          <BellIcon />
          <Text style={styles.navLabel}>Activity</Text>
          {unread > 0 ? (
            <View style={styles.badge}>
              <Text style={styles.badgeText}>{unread}</Text>
            </View>
          ) : null}
        </Pressable>
        <Pressable
          onPress={() => {
            closeDrawer();
            router.push("/(drawer)/self-driving");
          }}
          style={({ pressed }) => [styles.navRow, pressed && { opacity: 0.5 }]}
        >
          <SteeringIcon />
          <Text style={styles.navLabel}>Self-driving</Text>
          {newReports > 0 ? (
            <View style={styles.badge}>
              <Text style={styles.badgeText}>{newReports}</Text>
            </View>
          ) : null}
        </Pressable>
        <View style={styles.group}>
          <Text style={styles.groupTitle}>Recent tasks</Text>
          {tasks.isLoading && sorted.length === 0 ? (
            <Text style={styles.empty}>Loading</Text>
          ) : null}
          {sorted.map((task) => (
            <Host key={task.id} matchContents={{ vertical: true }}>
              <ContextMenu>
                <ContextMenu.Items>
                  <Button
                    label="Rename"
                    systemImage="pencil"
                    onPress={() => rename(task)}
                  />
                  <Button
                    label="Archive"
                    systemImage="archivebox"
                    onPress={() =>
                      updateTask.mutate({ id: task.id, archived: true })
                    }
                  />
                </ContextMenu.Items>
                <ContextMenu.Trigger>
                  <RNHostView matchContents>
                    <Pressable
                      onPress={() => open(task.id)}
                      style={({ pressed }) => [
                        styles.taskRow,
                        pressed && { opacity: 0.5 },
                      ]}
                    >
                      <View style={styles.taskBody}>
                        <Text style={styles.taskTitle} numberOfLines={2}>
                          {taskTitle(task)}
                        </Text>
                        <Text style={styles.taskAge}>
                          {formatRelativeAge(activityAt(task))}
                        </Text>
                      </View>
                      {isRunning(task) ? (
                        <ActivityIndicator
                          size="small"
                          color={colors.inkSoft}
                        />
                      ) : null}
                    </Pressable>
                  </RNHostView>
                </ContextMenu.Trigger>
              </ContextMenu>
            </Host>
          ))}
        </View>
      </ScrollView>
      <View
        style={[styles.footer, { paddingBottom: insets.bottom + 12 }]}
        pointerEvents="box-none"
      >
        <FadeScrim style={styles.footerScrim} color={colors.bgDeep} />
        <GlassCircleButton
          size={FOOTER_HEIGHT}
          onPress={() => router.push("/settings")}
        >
          <Text style={styles.avatarText}>
            {userName.slice(0, 2).toUpperCase()}
          </Text>
        </GlassCircleButton>
        <Pressable
          onPress={() => {
            closeDrawer();
            router.replace("/(drawer)");
          }}
          style={({ pressed }) => [styles.newTask, pressed && { opacity: 0.8 }]}
        >
          <Text style={styles.newTaskPlus}>+</Text>
          <Text style={styles.newTaskText}>New task</Text>
        </Pressable>
      </View>
    </View>
  );
}

const FOOTER_HEIGHT = 52;

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.bgDeep,
    paddingLeft: 18,
    paddingRight: 18 + 72,
    marginRight: -72,
  },
  wordmark: {
    fontFamily: fonts.sansBold,
    fontSize: 30,
    color: colors.ink,
    marginBottom: 18,
    marginLeft: 4,
  },
  scroll: { paddingBottom: 24, gap: 18 },
  navRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 8,
    paddingLeft: 4,
  },
  navLabel: {
    flex: 1,
    fontFamily: fonts.sansMedium,
    fontSize: 17,
    color: colors.ink,
  },
  badge: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 6,
  },
  badgeText: { fontFamily: fonts.sansSemi, fontSize: 12, color: "#FFFFFF" },
  group: { gap: 2 },
  groupTitle: {
    fontFamily: fonts.sansSemi,
    fontSize: 12,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.inkMute,
    paddingLeft: 4,
    marginBottom: 4,
  },
  taskRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    minHeight: 64,
    paddingVertical: 12,
    paddingHorizontal: 4,
  },
  taskBody: { flex: 1, minWidth: 0, gap: 3 },
  taskTitle: {
    fontFamily: fonts.sansMedium,
    fontSize: 17,
    lineHeight: 23,
    color: colors.ink,
  },
  taskAge: { fontFamily: fonts.sans, fontSize: 12, color: colors.inkSoft },
  empty: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.inkMute,
    paddingVertical: 6,
  },
  footer: {
    position: "absolute",
    left: 18,
    right: 18 + 72,
    bottom: 0,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingTop: 12,
  },
  footerScrim: {
    position: "absolute",
    left: -18,
    right: -(18 + 72),
    top: -36,
    bottom: 0,
  },
  avatarText: {
    fontSize: 14,
    fontFamily: fonts.sansBold,
    color: colors.ink,
  },
  newTask: {
    height: FOOTER_HEIGHT,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.dark,
    paddingLeft: 18,
    paddingRight: 24,
    borderRadius: radius.pill,
  },
  newTaskPlus: {
    color: colors.darkText,
    fontSize: 26,
    lineHeight: 28,
    fontFamily: fonts.sansMedium,
    marginTop: -2,
  },
  newTaskText: {
    color: colors.darkText,
    fontSize: 16,
    fontFamily: fonts.sansSemi,
  },
});
