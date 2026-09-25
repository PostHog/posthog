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
import { DrawerEdgeShadow } from "@/components/DrawerEdgeShadow";
import { FadeScrim } from "@/components/FadeScrim";
import { GlassCircleButton } from "@/components/Glass";
import { BellIcon, SearchIcon, SteeringIcon } from "@/components/Icons";
import { TaskListRow } from "@/components/TaskListRow";
import { useActivity } from "@/lib/activity";
import { useAuth } from "@/lib/auth";
import { useTasks } from "@/lib/queries";
import { useReports, useSeenReports } from "@/lib/reports";
import { colors, fonts, radius } from "@/lib/theme";

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
        <Text style={styles.sectionTitle}>Recent Tasks</Text>
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
            onPress={() => {
              closeDrawer();
              router.push({
                pathname: "/(drawer)/task/[id]",
                params: { id: task.id },
              });
            }}
          />
        ))}
        {tasks.isSuccess && tasks.data.length === 0 ? (
          <View style={styles.notice}>
            <Text style={styles.hint}>
              {tasks.hasNextPage
                ? "No cloud tasks in this page. Load more to continue."
                : "Your cloud tasks will appear here."}
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
  navigation: { gap: 10, marginBottom: 26 },
  navRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 10,
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
  sectionTitle: {
    fontFamily: fonts.sansSemi,
    fontSize: 14,
    color: colors.inkSoft,
    marginLeft: 4,
    marginBottom: 10,
  },
  hint: {
    fontFamily: fonts.sans,
    fontSize: 14,
    lineHeight: 20,
    color: colors.inkSoft,
  },
  notice: { paddingVertical: 16, paddingHorizontal: 4, gap: 6 },
  action: { paddingVertical: 12, paddingHorizontal: 4 },
  actionText: {
    fontFamily: fonts.sansMedium,
    fontSize: 14,
    color: colors.accent,
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
    fontFamily: fonts.sansSemi,
  },
});
