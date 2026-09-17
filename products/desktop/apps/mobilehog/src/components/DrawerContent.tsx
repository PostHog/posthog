import type { Task, TaskChannel } from "@posthog/shared/domain-types";
import { useRouter } from "expo-router";
import { type ReactElement, useMemo, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { DrawerEdgeShadow } from "@/components/DrawerEdgeShadow";
import { FadeScrim } from "@/components/FadeScrim";
import { GlassCircleButton } from "@/components/Glass";
import { BellIcon, Dot, LockIcon, SteeringIcon } from "@/components/Icons";
import { useActivity } from "@/lib/activity";
import { useAuth } from "@/lib/auth";
import { useChannels, useTasks } from "@/lib/queries";
import { useReports, useSeenReports } from "@/lib/reports";
import { colors, fonts, radius } from "@/lib/theme";

const PREVIEW_COUNT = 3;
const UNFILED = "tasks";

interface Space {
  key: string;
  name: string;
  personal: boolean;
  starred: boolean;
  tasks: Task[];
}

function groupSpaces(tasks: Task[], channels: TaskChannel[]): Space[] {
  const byChannel = new Map<string, Task[]>();
  const loose: Task[] = [];
  for (const task of tasks) {
    if (
      task.channel &&
      channels.some((channel) => channel.id === task.channel)
    ) {
      const list = byChannel.get(task.channel) ?? [];
      list.push(task);
      byChannel.set(task.channel, list);
    } else {
      loose.push(task);
    }
  }
  const spaces: Space[] = channels
    .map((channel) => ({
      key: channel.id,
      name: channel.system_role === "personal" ? "personal" : channel.name,
      personal: channel.system_role === "personal",
      starred: channel.starred || channel.system_role === "personal",
      tasks: byChannel.get(channel.id) ?? [],
    }))
    .filter((space) => space.tasks.length > 0 || space.starred);
  if (loose.length > 0) {
    spaces.push({
      key: UNFILED,
      name: "tasks",
      personal: false,
      starred: false,
      tasks: loose,
    });
  }
  // Personal first, then by name.
  return spaces.sort(
    (a, b) =>
      Number(b.personal) - Number(a.personal) || a.name.localeCompare(b.name),
  );
}

// Desktop's status dot: live states are solid, everything else a hollow ring.
function statusDot(task: Task): { color: string; hollow: boolean } {
  switch (task.latest_run?.status) {
    case "queued":
    case "not_started":
    case "in_progress":
      return { color: colors.accent, hollow: false };
    case "failed":
      return { color: colors.danger, hollow: false };
    default:
      return { color: colors.inkMute, hollow: true };
  }
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
  const channels = useChannels();
  const userName = useAuth((s) => s.session?.userName ?? "");
  const unread = useActivity().data?.unread_count ?? 0;
  const reports = useReports().data ?? [];
  const seenReports = useSeenReports((s) => s.seen);
  const newReports = reports.filter(
    (report) => !seenReports.has(report.id),
  ).length;
  // Starred spaces open by default, the rest closed; a toggle flips that.
  const [toggled, setToggled] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [groupsClosed, setGroupsClosed] = useState<Set<string>>(new Set());

  const spaces = useMemo(
    () => groupSpaces(tasks.data ?? [], channels.data ?? []),
    [tasks.data, channels.data],
  );
  const starred = spaces.filter((space) => space.starred);
  const rest = spaces.filter((space) => !space.starred);

  const flip = (
    set: Set<string>,
    update: (next: Set<string>) => void,
    key: string,
  ): void => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    update(next);
  };

  const open = (taskId: string): void => {
    closeDrawer();
    router.push({ pathname: "/(drawer)/task/[id]", params: { id: taskId } });
  };

  const renderSpace = (space: Space): ReactElement => {
    const isOpen = space.starred !== toggled.has(space.key);
    const isExpanded = expanded.has(space.key);
    const visible = isExpanded
      ? space.tasks
      : space.tasks.slice(0, PREVIEW_COUNT);
    const hidden = space.tasks.length - visible.length;
    return (
      <View key={space.key} style={styles.space}>
        <Pressable
          onPress={() => flip(toggled, setToggled, space.key)}
          style={({ pressed }) => [
            styles.spaceRow,
            pressed && { opacity: 0.5 },
          ]}
        >
          <Text style={[styles.chevron, isOpen && styles.chevronOpen]}>›</Text>
          {space.personal ? <LockIcon /> : null}
          <Text style={styles.spaceName} numberOfLines={1}>
            {space.name}
          </Text>
        </Pressable>
        {isOpen ? (
          <View style={styles.tree}>
            <View style={styles.treeLine} />
            {visible.map((task) => {
              const dot = statusDot(task);
              return (
                <Pressable
                  key={task.id}
                  onPress={() => open(task.id)}
                  style={({ pressed }) => [
                    styles.taskRow,
                    pressed && { opacity: 0.5 },
                  ]}
                >
                  <Dot color={dot.color} hollow={dot.hollow} />
                  <Text style={styles.taskTitle} numberOfLines={1}>
                    {taskTitle(task)}
                  </Text>
                </Pressable>
              );
            })}
            {space.tasks.length === 0 ? (
              <Text style={styles.empty}>Nothing here yet</Text>
            ) : null}
            {hidden > 0 || isExpanded ? (
              <Pressable
                onPress={() => flip(expanded, setExpanded, space.key)}
                style={({ pressed }) => [
                  styles.viewAllRow,
                  pressed && { opacity: 0.5 },
                ]}
              >
                <View style={styles.treeElbow} />
                <Text style={styles.viewAll}>
                  {isExpanded ? "view less" : "view all"}
                </Text>
                {!isExpanded ? (
                  <Text style={styles.viewAllCount}>{space.tasks.length}</Text>
                ) : null}
              </Pressable>
            ) : null}
          </View>
        ) : null}
      </View>
    );
  };

  const renderGroup = (
    key: string,
    label: string,
    list: Space[],
  ): ReactElement | null => {
    if (list.length === 0) return null;
    const closed = groupsClosed.has(key);
    return (
      <View style={styles.group}>
        <Pressable
          onPress={() => flip(groupsClosed, setGroupsClosed, key)}
          hitSlop={6}
          style={styles.groupHeader}
        >
          <Text style={styles.groupTitle}>{label}</Text>
          <Text style={[styles.groupChevron, !closed && styles.chevronOpen]}>
            ›
          </Text>
        </Pressable>
        {closed ? null : list.map(renderSpace)}
      </View>
    );
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
        {tasks.isLoading && spaces.length === 0 ? (
          <Text style={styles.empty}>Loading</Text>
        ) : null}
        {renderGroup("starred", "Starred", starred)}
        {renderGroup("spaces", "Spaces", rest)}
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

const CHEVRON_WIDTH = 18;
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
  groupHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 4,
    paddingLeft: 4,
    marginBottom: 2,
  },
  groupTitle: {
    fontFamily: fonts.sansSemi,
    fontSize: 12,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.inkMute,
  },
  groupChevron: { fontSize: 16, lineHeight: 18, color: colors.inkMute },
  space: { marginBottom: 2 },
  spaceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
  },
  chevron: {
    width: CHEVRON_WIDTH,
    textAlign: "center",
    fontSize: 20,
    lineHeight: 22,
    color: colors.inkSoft,
  },
  chevronOpen: { transform: [{ rotate: "90deg" }] },
  spaceName: {
    flex: 1,
    fontFamily: fonts.sansMedium,
    fontSize: 16,
    color: colors.ink,
  },
  tree: { paddingLeft: CHEVRON_WIDTH + 8 },
  treeLine: {
    position: "absolute",
    left: CHEVRON_WIDTH / 2,
    top: 0,
    bottom: 22,
    width: 1.5,
    backgroundColor: colors.line,
  },
  taskRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
  },
  taskTitle: {
    flex: 1,
    fontFamily: fonts.sansMedium,
    fontSize: 15,
    color: colors.ink,
  },
  empty: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.inkMute,
    paddingVertical: 6,
  },
  viewAllRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 6,
    marginLeft: -(CHEVRON_WIDTH / 2) - 8,
  },
  treeElbow: {
    width: 22,
    height: 12,
    borderLeftWidth: 1.5,
    borderBottomWidth: 1.5,
    borderColor: colors.line,
    borderBottomLeftRadius: 8,
    marginTop: -12,
  },
  viewAll: { fontFamily: fonts.sans, fontSize: 15, color: colors.inkSoft },
  viewAllCount: { fontFamily: fonts.sans, fontSize: 13, color: colors.inkMute },
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
