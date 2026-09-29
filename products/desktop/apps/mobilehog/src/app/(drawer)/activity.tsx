import { useNavigation, useRouter } from "expo-router";
import { useMemo, useState } from "react";
import {
  Pressable,
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
import { MenuIcon } from "@/components/Icons";
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
  const [unreadsOnly, setUnreadsOnly] = useState(false);
  const [query, setQuery] = useState("");

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rows = toRows(activity.data, email, name).filter(
      (row) =>
        (!unreadsOnly || row.item.isUnread) &&
        (!needle || row.item.taskTitle.toLowerCase().includes(needle)),
    );
    return groupByDay(rows);
  }, [activity.data, email, name, unreadsOnly, query]);

  const open = (row: ActivityRow): void => {
    if (row.item.isUnread) markRead.mutate(row.item);
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
        <View style={styles.unreads}>
          <Text style={styles.unreadsLabel}>Unreads</Text>
          <Switch
            value={unreadsOnly}
            onValueChange={setUnreadsOnly}
            trackColor={{ true: colors.accent }}
          />
        </View>
      </View>
      <ScrollView
        contentContainerStyle={[
          styles.scroll,
          { paddingBottom: insets.bottom + 24 },
        ]}
        keyboardDismissMode="on-drag"
      >
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
        {groups.length === 0 ? (
          <Text style={styles.empty}>
            {activity.isLoading ? "Loading" : "Nothing here"}
          </Text>
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
                  pressed && { opacity: 0.5 },
                ]}
              >
                {row.icon ? (
                  <AgentGlyph icon={row.icon} />
                ) : (
                  <View style={styles.avatar}>
                    <Text style={styles.avatarText}>{row.initials}</Text>
                  </View>
                )}
                <View style={styles.body}>
                  <Text
                    style={[
                      styles.rowTitle,
                      row.item.isUnread && styles.rowTitleUnread,
                    ]}
                    numberOfLines={1}
                  >
                    {row.item.taskTitle}
                  </Text>
                  <View style={styles.metaRow}>
                    <Text style={styles.meta} numberOfLines={1}>
                      {row.metadata}
                    </Text>
                    {row.space ? (
                      <Text style={styles.spaceChip} numberOfLines={1}>
                        {row.space}
                      </Text>
                    ) : null}
                  </View>
                  {row.item.snippet ? (
                    <Text style={styles.snippet} numberOfLines={2}>
                      {row.item.snippet}
                    </Text>
                  ) : null}
                </View>
                {row.item.isUnread ? <View style={styles.unreadDot} /> : null}
              </Pressable>
            ))}
          </View>
        ))}
      </ScrollView>
    </DrawerScene>
  );
}

const styles = StyleSheet.create({
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
  scroll: { paddingHorizontal: 16, gap: 18, paddingTop: 6 },
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
  glyph: {
    width: 30,
    height: 30,
    borderRadius: 8,
    backgroundColor: "#FFFFFF",
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
  metaRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  meta: {
    flexShrink: 1,
    fontFamily: fonts.sans,
    fontSize: 13,
    color: colors.inkMute,
  },
  spaceChip: {
    fontFamily: fonts.sansMedium,
    fontSize: 12,
    color: colors.inkSoft,
    backgroundColor: colors.bgDeep,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 5,
    overflow: "hidden",
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
