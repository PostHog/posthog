import { useRouter } from "expo-router";
import { useState } from "react";
import {
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { DrawerEdgeShadow } from "@/components/DrawerEdgeShadow";
import { FadeScrim } from "@/components/FadeScrim";
import { GlassCircleButton } from "@/components/Glass";
import { BellIcon, SearchIcon, SteeringIcon } from "@/components/Icons";
import { OptionsSheet } from "@/components/OptionsSheet";
import { TaskListRow } from "@/components/TaskListRow";
import { useActivity } from "@/lib/activity";
import { useAuth } from "@/lib/auth";
import { useTasks } from "@/lib/queries";
import { useReports, useSeenReports } from "@/lib/reports";
import { colors, fonts, radius } from "@/lib/theme";

export function DrawerContent({ closeDrawer }: { closeDrawer: () => void }) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [filter, setFilter] = useState<keyof typeof TASK_FILTERS>("all");
  const [archived, setArchived] = useState(false);
  const [showOptions, setShowOptions] = useState(false);
  const tasks = useTasks(
    "",
    true,
    filter === "all" ? undefined : filter,
    archived,
  );
  const userName = useAuth((s) => s.session?.userName ?? "");
  const activity = useActivity().data;
  const unread = activity?.unread_count ?? 0;
  const unreadTasks = new Set(
    activity?.results.filter((row) => row.is_unread).map((row) => row.task_id),
  );
  const reports = useReports().data ?? [];
  const seenReports = useSeenReports((s) => s.seen);
  const newReports = reports.filter(
    (report) => !seenReports.has(report.id),
  ).length;
  const [refreshing, setRefreshing] = useState(false);

  const refresh = async (): Promise<void> => {
    if (refreshing || tasks.isFetching) return;
    setRefreshing(true);
    try {
      await tasks.refetch();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <View style={[styles.root, { paddingTop: insets.top + 18 }]}>
      {showOptions ? (
        <OptionsSheet
          title="Tasks"
          onClose={() => setShowOptions(false)}
          options={[
            { label: "View archived", onPress: () => setArchived(true) },
          ]}
        />
      ) : null}
      <DrawerEdgeShadow />
      <View style={styles.header}>
        <Text style={styles.wordmark}>PostHog</Text>
        <GlassCircleButton
          accessibilityLabel="Search tasks"
          size={44}
          onPress={() => {
            closeDrawer();
            router.push("/search");
          }}
        >
          <SearchIcon />
        </GlassCircleButton>
      </View>
      <ScrollView
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void refresh()}
            tintColor={colors.inkMute}
          />
        }
        contentContainerStyle={[
          styles.scroll,
          { paddingBottom: FOOTER_HEIGHT + insets.bottom + 24 },
        ]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.navigation}>
          <Pressable
            accessibilityRole="button"
            onPress={() => {
              closeDrawer();
              router.push("/(drawer)/activity");
            }}
            style={({ pressed }) => [
              styles.navRow,
              pressed && { opacity: 0.5 },
            ]}
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
            accessibilityRole="button"
            onPress={() => {
              closeDrawer();
              router.push("/(drawer)/self-driving");
            }}
            style={({ pressed }) => [
              styles.navRow,
              pressed && { opacity: 0.5 },
            ]}
          >
            <SteeringIcon />
            <Text style={styles.navLabel}>Self-driving</Text>
            {newReports > 0 ? (
              <View style={styles.badge}>
                <Text style={styles.badgeText}>{newReports}</Text>
              </View>
            ) : null}
          </Pressable>
        </View>
        <View style={styles.taskHeader}>
          <Text accessibilityRole="header" style={styles.sectionTitle}>
            {archived ? "Archived tasks" : "Tasks"}
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={
              archived ? "Back to tasks" : "Task list options"
            }
            style={styles.listOptions}
            onPress={() =>
              archived ? setArchived(false) : setShowOptions(true)
            }
          >
            <Text style={styles.listOptionsText}>
              {archived ? "Back" : "⋯"}
            </Text>
          </Pressable>
        </View>
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.filters}
        >
          {(Object.keys(TASK_FILTERS) as Array<keyof typeof TASK_FILTERS>).map(
            (value) => (
              <Pressable
                key={value}
                accessibilityRole="button"
                accessibilityLabel={`${TASK_FILTERS[value]} tasks`}
                accessibilityState={{ selected: filter === value }}
                onPress={() => setFilter(value)}
                style={({ pressed }) => [
                  styles.filter,
                  filter === value && styles.filterSelected,
                  pressed && { opacity: 0.5 },
                ]}
              >
                <Text
                  style={[
                    styles.filterText,
                    filter === value && styles.filterTextSelected,
                  ]}
                >
                  {TASK_FILTERS[value]}
                </Text>
              </Pressable>
            ),
          )}
        </ScrollView>
        <ConnectionBanner />
        {tasks.isLoading ? (
          <Text style={styles.hint}>Loading tasks</Text>
        ) : null}
        {tasks.isError ? (
          <View style={styles.notice}>
            <Text style={styles.hint}>Could not load tasks.</Text>
            <Pressable
              accessibilityRole="button"
              disabled={tasks.isFetching}
              onPress={() => void tasks.refetch()}
              style={styles.action}
            >
              <Text style={styles.actionText}>
                {tasks.isFetching ? "Loading" : "Retry"}
              </Text>
            </Pressable>
          </View>
        ) : null}
        {tasks.data.map((task) => (
          <TaskListRow
            key={task.id}
            task={task}
            unread={unreadTasks.has(task.id)}
            onPress={() => {
              closeDrawer();
              router.push({
                pathname: "/(drawer)/task/[id]",
                params: {
                  id: task.id,
                  archived: String(archived),
                },
              });
            }}
          />
        ))}
        {tasks.isSuccess && tasks.data.length === 0 ? (
          <View style={styles.notice}>
            <Text style={styles.hint}>
              {tasks.hasNextPage
                ? "No cloud tasks in this page. Load more to continue."
                : filter !== "all"
                  ? "No tasks match this status. Select All to see other tasks."
                  : archived
                    ? "No archived tasks. Tasks you archive will appear here."
                    : "No tasks yet. Start a new task below."}
            </Text>
          </View>
        ) : null}
        {tasks.hasNextPage ? (
          <Pressable
            accessibilityRole="button"
            disabled={tasks.isFetching}
            onPress={() => void tasks.fetchNextPage()}
            style={styles.action}
          >
            <Text style={styles.actionText}>
              {tasks.isFetchingNextPage ? "Loading" : "Load more tasks"}
            </Text>
          </Pressable>
        ) : null}
      </ScrollView>
      <View
        style={[styles.footer, { paddingBottom: insets.bottom + 12 }]}
        pointerEvents="box-none"
      >
        <FadeScrim style={styles.footerScrim} color={colors.bgDeep} />
        <GlassCircleButton
          accessibilityLabel="Settings"
          size={FOOTER_HEIGHT}
          onPress={() => router.push("/settings")}
        >
          <Text style={styles.avatarText}>
            {userName.slice(0, 2).toUpperCase()}
          </Text>
        </GlassCircleButton>
        <Pressable
          accessibilityRole="button"
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

const TASK_FILTERS = {
  all: "All",
  in_progress: "Running",
  failed: "Failed",
  queued: "Queued",
  completed: "Done",
} as const;

const FOOTER_HEIGHT = 52;
const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.bgDeep,
    paddingLeft: 18,
    paddingRight: 18 + 72,
    marginRight: -72,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 22,
    gap: 12,
  },
  wordmark: {
    fontFamily: fonts.sansBold,
    fontSize: 30,
    color: colors.ink,
    marginLeft: 4,
  },
  scroll: { paddingBottom: 24 },
  navigation: { gap: 4, marginBottom: 20 },
  navRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 10,
    paddingLeft: 4,
  },
  navLabel: {
    flex: 1,
    fontWeight: "500",
    fontSize: 16,
    lineHeight: 22,
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
  badgeText: { fontWeight: "600", fontSize: 12, color: "#FFFFFF" },
  taskHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingLeft: 4,
    gap: 8,
  },
  sectionTitle: {
    flexShrink: 1,
    fontWeight: "600",
    fontSize: 16,
    lineHeight: 22,
    color: colors.ink,
  },
  listOptions: {
    flexShrink: 0,
    minWidth: 44,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  listOptionsText: { fontSize: 16, fontWeight: "500", color: colors.inkSoft },
  filters: {
    gap: 4,
    paddingVertical: 4,
    paddingHorizontal: 4,
    marginBottom: 4,
  },
  filter: {
    minHeight: 44,
    minWidth: 44,
    paddingHorizontal: 8,
    justifyContent: "center",
    alignItems: "center",
    borderRadius: 12,
  },
  filterSelected: { backgroundColor: colors.fill },
  filterText: {
    fontSize: 13,
    lineHeight: 18,
    fontWeight: "500",
    color: colors.inkSoft,
  },
  filterTextSelected: { color: colors.ink, fontWeight: "600" },
  hint: {
    fontSize: 13,
    lineHeight: 20,
    color: colors.inkSoft,
  },
  notice: { paddingVertical: 16, paddingHorizontal: 4, gap: 6 },
  action: { paddingVertical: 12, paddingHorizontal: 4 },
  actionText: {
    fontWeight: "500",
    fontSize: 14,
    color: colors.ink,
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
  avatarText: { fontSize: 14, fontFamily: fonts.sansBold, color: colors.ink },
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
    fontWeight: "600",
  },
});
