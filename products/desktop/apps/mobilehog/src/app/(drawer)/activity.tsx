import { useNavigation, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import {
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { DrawerScene } from "@/components/DrawerScene";
import { Glass, GlassCircleButton } from "@/components/Glass";
import { BellIcon, MenuIcon } from "@/components/Icons";
import { ListState } from "@/components/ListState";
import {
  type ActivityRow,
  groupByDay,
  toRows,
  useActivity,
  useMarkActivityRead,
} from "@/lib/activity";
import { useAuth } from "@/lib/auth";
import { colors, fonts, radius } from "@/lib/theme";

function AgentGlyph({ icon }: { icon: NonNullable<ActivityRow["icon"]> }) {
  const glyph = icon === "check" ? "✓" : icon === "question" ? "?" : "…";
  return (
    <View style={[styles.glyph, icon === "check" && styles.glyphAccent]}>
      <Text
        style={[styles.glyphText, icon === "check" && styles.glyphTextAccent]}
      >
        {glyph}
      </Text>
    </View>
  );
}

export default function ActivityScreen() {
  const router = useRouter();
  const navigation = useNavigation<{ openDrawer: () => void }>();
  const insets = useSafeAreaInsets();
  const email = useAuth((s) => s.session?.email ?? null);
  const name = useAuth((s) => s.session?.userName ?? null);
  const activity = useActivity();
  const markRead = useMarkActivityRead();
  const [unreadsOnly, setUnreadsOnly] = useState(true);
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const hasActivity = (activity.data?.results.length ?? 0) > 0;

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rows = toRows(activity.data, email, name).filter(
      (row) =>
        (!unreadsOnly || row.item.isUnread) &&
        (!needle || row.item.taskTitle.toLowerCase().includes(needle)),
    );
    return groupByDay(rows);
  }, [activity.data, email, name, unreadsOnly, query]);

  const unreadItems = groups.flatMap((group) =>
    group.rows.filter((row) => row.item.isUnread).map((row) => row.item),
  );
  const refresh = async (): Promise<void> => {
    if (activity.isFetching || refreshing) return;
    setRefreshing(true);
    try {
      await activity.refetch();
    } finally {
      setRefreshing(false);
    }
  };

  const open = (row: ActivityRow): void => {
    if (row.item.isUnread)
      markRead.mutate([row.item], {
        onError: () =>
          Alert.alert(
            "Could not mark activity as read",
            "Try again from Activity.",
          ),
      });
    router.push({
      pathname: "/(drawer)/task/[id]",
      params: { id: row.item.taskId },
    });
  };

  return (
    <DrawerScene>
      <View style={[styles.header, { paddingTop: insets.top + 6 }]}>
        <GlassCircleButton onPress={() => navigation.openDrawer()}>
          <MenuIcon />
        </GlassCircleButton>
        <Text style={styles.title}>Activity</Text>
        {hasActivity ? (
          <View style={styles.unreads}>
            <Text style={styles.unreadsLabel}>Unread</Text>
            <Switch
              value={unreadsOnly}
              onValueChange={setUnreadsOnly}
              trackColor={{ true: colors.accent }}
            />
          </View>
        ) : null}
      </View>
      <ScrollView
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void refresh()}
          />
        }
        contentContainerStyle={[
          styles.scroll,
          { paddingBottom: insets.bottom + 24 },
        ]}
        keyboardDismissMode="on-drag"
        keyboardShouldPersistTaps="handled"
      >
        {hasActivity || query ? (
          <Glass style={styles.search}>
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Search activity"
              placeholderTextColor={colors.inkMute}
              style={styles.searchInput}
              autoCorrect={false}
            />
          </Glass>
        ) : null}
        {unreadItems.length > 0 ? (
          <Pressable
            accessibilityRole="button"
            disabled={markRead.isPending}
            onPress={() => markRead.mutate(unreadItems)}
            style={styles.readAction}
          >
            <Text style={styles.actionText}>
              {markRead.isPending ? "Saving" : "Mark as read"}
            </Text>
          </Pressable>
        ) : null}
        {markRead.isError ? (
          <Text style={styles.empty}>
            Could not mark activity as read. Try again.
          </Text>
        ) : null}
        {activity.isError ? (
          <ListState
            title="Could not load activity"
            description="Check your connection and try again."
            icon={<BellIcon />}
            action={{
              label: "Retry",
              onPress: () => void activity.refetch(),
              disabled: activity.isFetching,
            }}
          />
        ) : groups.length === 0 ? (
          <ListState
            loading={activity.isLoading}
            icon={<BellIcon />}
            title={
              activity.isLoading
                ? "Loading activity"
                : query.trim()
                  ? "No matching activity"
                  : activity.hasNextPage
                    ? "No unread activity in this page"
                    : hasActivity && unreadsOnly
                      ? "No unread activity"
                      : "No activity yet"
            }
            description={
              activity.isLoading
                ? undefined
                : query.trim()
                  ? "Try another task title."
                  : activity.hasNextPage
                    ? "Load more to check older activity."
                    : hasActivity && unreadsOnly
                      ? "You have read all your updates."
                      : "Task updates and replies will appear here."
            }
            action={
              activity.isLoading
                ? undefined
                : query.trim()
                  ? { label: "Clear search", onPress: () => setQuery("") }
                  : hasActivity && unreadsOnly
                    ? {
                        label: "View all activity",
                        onPress: () => setUnreadsOnly(false),
                      }
                    : undefined
            }
          />
        ) : null}
        {groups.map((group) => (
          <View key={group.label} style={styles.group}>
            <Text style={styles.groupTitle}>{group.label}</Text>
            {group.rows.map((row) => (
              <Pressable
                key={row.item.id}
                onPress={() => open(row)}
                style={({ pressed }) => [
                  styles.row,
                  row.item.isUnread && styles.rowUnread,
                  pressed && { opacity: 0.5 },
                ]}
              >
                {row.icon ? (
                  <View style={!row.item.isUnread && styles.readGlyph}>
                    <AgentGlyph icon={row.icon} />
                  </View>
                ) : (
                  <View
                    style={[
                      styles.avatar,
                      !row.item.isUnread && styles.readGlyph,
                    ]}
                  >
                    <Text style={styles.avatarText}>{row.initials}</Text>
                  </View>
                )}
                <View style={styles.body}>
                  {row.item.isUnread ? (
                    <Text style={styles.unreadLabel}>NEW</Text>
                  ) : null}
                  <Text
                    style={[
                      styles.rowTitle,
                      row.item.isUnread && styles.rowTitleUnread,
                    ]}
                    numberOfLines={1}
                  >
                    {row.item.taskTitle}
                  </Text>
                  <Text style={styles.meta} numberOfLines={1}>
                    {row.metadata}
                  </Text>
                  {row.item.snippet ? (
                    <Text style={styles.snippet} numberOfLines={2}>
                      {row.item.snippet}
                    </Text>
                  ) : null}
                </View>
                {row.item.isUnread ? (
                  <Pressable
                    accessibilityRole="button"
                    accessibilityLabel="Mark as read"
                    disabled={markRead.isPending}
                    hitSlop={8}
                    onPress={(event) => {
                      event.stopPropagation();
                      markRead.mutate([row.item]);
                    }}
                    style={styles.readAction}
                  >
                    <Text style={styles.actionText}>✓</Text>
                  </Pressable>
                ) : null}
              </Pressable>
            ))}
          </View>
        ))}
        {activity.hasNextPage ? (
          <Pressable
            disabled={activity.isFetchingNextPage}
            onPress={() => void activity.fetchNextPage()}
            style={styles.readAction}
          >
            <Text style={styles.actionText}>
              {activity.isFetchingNextPage ? "Loading" : "Load more"}
            </Text>
          </Pressable>
        ) : null}
      </ScrollView>
    </DrawerScene>
  );
}

const styles = StyleSheet.create({
  readAction: { paddingVertical: 8, paddingHorizontal: 4 },
  actionText: {
    fontFamily: fonts.sansMedium,
    fontSize: 14,
    color: colors.accent,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
    paddingBottom: 8,
  },
  title: {
    flex: 1,
    fontFamily: fonts.sansBold,
    fontSize: 26,
    color: colors.ink,
  },
  unreads: { flexDirection: "row", alignItems: "center", gap: 8 },
  unreadsLabel: { fontFamily: fonts.sans, fontSize: 15, color: colors.inkSoft },
  scroll: { flexGrow: 1, paddingHorizontal: 16, gap: 18, paddingTop: 6 },
  search: {
    borderRadius: radius.pill,
    paddingHorizontal: 16,
    overflow: "hidden",
  },
  searchInput: {
    fontFamily: fonts.sans,
    fontSize: 16,
    color: colors.ink,
    paddingVertical: 12,
  },
  empty: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.inkMute,
    paddingTop: 12,
  },
  group: { gap: 2 },
  groupTitle: {
    fontFamily: fonts.sansSemi,
    fontSize: 12,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.inkMute,
    marginBottom: 6,
    marginLeft: 4,
  },
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
    paddingVertical: 10,
    paddingHorizontal: 4,
  },
  rowUnread: {
    backgroundColor: colors.fill,
    borderRadius: 14,
    paddingHorizontal: 10,
  },
  readGlyph: { opacity: 0.5 },
  unreadLabel: {
    fontFamily: fonts.sansBold,
    fontSize: 11,
    letterSpacing: 1,
    color: colors.accent,
  },
  glyph: {
    width: 30,
    height: 30,
    borderRadius: 8,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 2,
  },
  glyphAccent: { backgroundColor: colors.accent },
  glyphText: {
    fontFamily: fonts.sansBold,
    fontSize: 14,
    color: colors.inkSoft,
  },
  glyphTextAccent: { color: "#FFFFFF" },
  avatar: {
    width: 30,
    height: 30,
    borderRadius: 8,
    backgroundColor: colors.bgDeep,
    alignItems: "center",
    justifyContent: "center",
    marginTop: 2,
  },
  avatarText: { fontFamily: fonts.sansBold, fontSize: 11, color: colors.ink },
  body: { flex: 1, gap: 2 },
  rowTitle: { fontFamily: fonts.sansMedium, fontSize: 16, color: colors.ink },
  rowTitleUnread: { fontFamily: fonts.sansSemi },
  meta: {
    fontFamily: fonts.sans,
    fontSize: 13,
    color: colors.inkMute,
  },
  snippet: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.inkSoft,
    marginTop: 2,
  },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.accent,
    marginTop: 8,
  },
});
