import type { Task, TaskChannel } from "@posthog/shared/domain-types";
import { useRouter } from "expo-router";
import { useMemo, useState } from "react";
import {
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { DrawerEdgeShadow } from "@/components/DrawerEdgeShadow";
import { GlassCircleButton } from "@/components/Glass";
import { Dot } from "@/components/Icons";
import { useAuth } from "@/lib/auth";
import { useChannels, useTasks } from "@/lib/queries";
import { colors, fonts, radius } from "@/lib/theme";

const LIVE: ReadonlySet<string> = new Set([
  "queued",
  "in_progress",
  "not_started",
]);
const PREVIEW_COUNT = 3;
// How far the drawer extends under the chat layer, so its edge frosts content.
export const UNDERLAP = 72;

interface Section {
  key: string;
  title: string;
  tasks: Task[];
}

function groupTasks(tasks: Task[], channels: TaskChannel[]): Section[] {
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
  const sections: Section[] = [];
  for (const channel of channels) {
    const list = byChannel.get(channel.id);
    if (list?.length) {
      const name =
        channel.system_role === "personal" ? "personal" : channel.name;
      sections.push({ key: channel.id, title: `# ${name}`, tasks: list });
    }
  }
  if (loose.length || sections.length === 0) {
    sections.push({ key: "tasks", title: "Tasks", tasks: loose });
  }
  return sections;
}

export function DrawerContent({ closeDrawer }: { closeDrawer: () => void }) {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const tasks = useTasks();
  const channels = useChannels();
  const logout = useAuth((s) => s.logout);
  const userName = useAuth((s) => s.session?.userName ?? "");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggle = (
    set: Set<string>,
    update: (next: Set<string>) => void,
    key: string,
  ): void => {
    const next = new Set(set);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    update(next);
  };

  const sections = useMemo(
    () => groupTasks(tasks.data ?? [], channels.data ?? []),
    [tasks.data, channels.data],
  );

  const open = (taskId: string): void => {
    closeDrawer();
    router.push({ pathname: "/(drawer)/task/[id]", params: { id: taskId } });
  };

  return (
    <View
      style={[
        styles.root,
        { paddingTop: insets.top + 18, paddingBottom: insets.bottom + 12 },
      ]}
    >
      <DrawerEdgeShadow />
      <Text style={styles.wordmark}>PostHog</Text>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {sections.map((section) => {
          const isCollapsed = collapsed.has(section.key);
          const isExpanded = expanded.has(section.key);
          const visible = isExpanded
            ? section.tasks
            : section.tasks.slice(0, PREVIEW_COUNT);
          const hidden = section.tasks.length - visible.length;
          return (
            <View key={section.key} style={styles.section}>
              <Pressable
                onPress={() => toggle(collapsed, setCollapsed, section.key)}
                style={styles.sectionHeader}
                hitSlop={6}
              >
                <Text style={styles.sectionTitle}>{section.title}</Text>
                <Text
                  style={[
                    styles.sectionChevron,
                    !isCollapsed && styles.sectionChevronOpen,
                  ]}
                >
                  ›
                </Text>
              </Pressable>
              {isCollapsed ? null : (
                <>
                  {section.tasks.length === 0 ? (
                    <Text style={styles.empty}>
                      {tasks.isLoading
                        ? "Loading"
                        : "Nothing yet. Start a chat."}
                    </Text>
                  ) : null}
                  {visible.map((task) => {
                    const live =
                      !!task.latest_run?.status &&
                      LIVE.has(task.latest_run.status);
                    return (
                      <Pressable
                        key={task.id}
                        onPress={() => open(task.id)}
                        style={({ pressed }) => [
                          styles.row,
                          pressed && { opacity: 0.5 },
                        ]}
                      >
                        <Dot color={live ? colors.accent : colors.inkMute} />
                        <Text style={styles.rowText} numberOfLines={1}>
                          {task.title ||
                            task.description_preview ||
                            task.description ||
                            "Untitled"}
                        </Text>
                      </Pressable>
                    );
                  })}
                  {hidden > 0 || isExpanded ? (
                    <Pressable
                      onPress={() => toggle(expanded, setExpanded, section.key)}
                      style={({ pressed }) => [
                        styles.row,
                        pressed && { opacity: 0.5 },
                      ]}
                    >
                      <View style={styles.moreDot} />
                      <Text style={styles.moreText}>
                        {isExpanded ? "Less" : `${hidden} more`}
                      </Text>
                    </Pressable>
                  ) : null}
                </>
              )}
            </View>
          );
        })}
      </ScrollView>
      <View style={styles.footer}>
        <GlassCircleButton
          size={44}
          tint="rgba(255,92,28,0.18)"
          onPress={() =>
            Alert.alert("Sign out?", undefined, [
              { text: "Cancel", style: "cancel" },
              {
                text: "Sign out",
                style: "destructive",
                onPress: () => logout(),
              },
            ])
          }
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
          style={({ pressed }) => [styles.newChat, pressed && { opacity: 0.8 }]}
        >
          <Text style={styles.newChatText}>+ New chat</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.bgDeep,
    paddingLeft: 22,
    paddingRight: 22 + UNDERLAP,
    marginRight: -UNDERLAP,
  },
  wordmark: {
    fontFamily: fonts.serif,
    fontSize: 32,
    color: colors.ink,
    marginBottom: 22,
  },
  scroll: { paddingBottom: 24, gap: 22 },
  section: { gap: 2 },
  sectionHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 8,
  },
  sectionTitle: { fontFamily: fonts.sans, fontSize: 15, color: colors.inkMute },
  sectionChevron: {
    fontFamily: fonts.sans,
    fontSize: 18,
    lineHeight: 20,
    color: colors.inkMute,
  },
  sectionChevronOpen: { transform: [{ rotate: "90deg" }] },
  moreDot: { width: 7, height: 7 },
  moreText: { fontFamily: fonts.sans, fontSize: 15, color: colors.inkMute },
  empty: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.inkMute,
    paddingVertical: 6,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 16,
    paddingVertical: 11,
  },
  rowText: { flex: 1, fontFamily: fonts.sans, fontSize: 17, color: colors.ink },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingTop: 8,
  },
  avatarText: {
    fontSize: 13,
    fontFamily: fonts.sansBold,
    color: colors.accent,
  },
  newChat: {
    backgroundColor: colors.dark,
    paddingHorizontal: 22,
    paddingVertical: 14,
    borderRadius: radius.pill,
  },
  newChatText: {
    color: colors.darkText,
    fontSize: 16,
    fontFamily: fonts.sansSemi,
  },
});
