import { useRouter } from "expo-router";
import { useMemo } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { DrawerEdgeShadow } from "@/components/DrawerEdgeShadow";
import { FadeScrim } from "@/components/FadeScrim";
import { GlassCircleButton } from "@/components/Glass";
import { BellIcon, SteeringIcon } from "@/components/Icons";
import { activityAt, RowSkeletons, TaskRow } from "@/components/TaskRow";
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
  const sorted = useMemo(
    () =>
      [...(tasks.data ?? [])].sort((a, b) =>
        activityAt(b).localeCompare(activityAt(a)),
      ),
    [tasks.data],
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
          {tasks.isLoading && sorted.length === 0 ? <RowSkeletons /> : null}
          {sorted.map((task) => (
            <TaskRow key={task.id} task={task} onPress={() => open(task.id)} />
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
