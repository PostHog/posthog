import { Button, Host, Image, Menu } from "@expo/ui/swift-ui";
import { frame, glassEffect } from "@expo/ui/swift-ui/modifiers";
import type { SignalReport, Task } from "@posthog/shared/domain-types";
import { FlashList } from "@shopify/flash-list";
import { useNavigation, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";
import { KeyboardStickyView } from "react-native-keyboard-controller";
import Animated, {
  FadeIn,
  FadeInDown,
  FadeOut,
  FadeOutDown,
  LinearTransition,
  ZoomIn,
  ZoomOut,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { DrawerScene } from "@/components/DrawerScene";
import { FadeScrim } from "@/components/FadeScrim";
import { Glass, GlassCircleButton } from "@/components/Glass";
import { MenuIcon } from "@/components/Icons";
import {
  activityAt,
  ListRow,
  RowSkeletons,
  TaskRow,
} from "@/components/TaskRow";
import { useTaskPages } from "@/lib/queries";
import { useReports } from "@/lib/reports";
import { colors, fonts, radius } from "@/lib/theme";

type Scope = "all" | "tasks" | "reports" | "archived";

type Item =
  | { kind: "task"; id: string; time: string; task: Task }
  | { kind: "report"; id: string; time: string; report: SignalReport };

const SCOPES = [
  { value: "all", label: "All", icon: "bubble.left.and.bubble.right" },
  { value: "tasks", label: "Tasks", icon: "bubble.left" },
  { value: "reports", label: "Self-driving", icon: "steeringwheel" },
  { value: "archived", label: "Archived", icon: "archivebox" },
] as const;

const HEADER_HEIGHT = 64;

function useDebounced(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

export default function RecentsScreen() {
  const router = useRouter();
  const navigation = useNavigation<{ openDrawer: () => void }>();
  const insets = useSafeAreaInsets();
  const input = useRef<TextInput>(null);
  const [searching, setSearching] = useState(true);
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<Scope>("all");
  const search = useDebounced(query.trim(), 250);
  const archived = scope === "archived";
  const showReports = scope === "all" || scope === "reports";
  const tasks = useTaskPages(search, archived);
  const reports = useReports(search);

  const items = useMemo(() => {
    const list: Item[] = [];
    if (scope !== "reports") {
      for (const task of tasks.data?.pages.flatMap((page) => page.visible) ??
        []) {
        list.push({ kind: "task", id: task.id, time: activityAt(task), task });
      }
    }
    if (showReports) {
      for (const report of reports.data ?? []) {
        list.push({
          kind: "report",
          id: report.id,
          time: report.updated_at,
          report,
        });
      }
    }
    return list.sort((a, b) => b.time.localeCompare(a.time));
  }, [scope, showReports, tasks.data, reports.data]);

  const loading =
    (scope !== "reports" && tasks.isLoading) ||
    (showReports && reports.isLoading);

  const closeSearch = (): void => {
    setQuery("");
    input.current?.blur();
    setSearching(false);
  };

  const top = insets.top + HEADER_HEIGHT;

  return (
    <DrawerScene>
      <FlashList
        data={items}
        keyExtractor={(item) => `${item.kind}-${item.id}`}
        getItemType={(item) => item.kind}
        renderItem={({ item }) =>
          item.kind === "task" ? (
            <TaskRow
              task={item.task}
              label="Task"
              archived={archived}
              onPress={() =>
                router.push({
                  pathname: "/(drawer)/task/[id]",
                  params: { id: item.id },
                })
              }
            />
          ) : (
            <ListRow
              title={item.report.title ?? "Untitled report"}
              label="Report"
              time={item.time}
              onPress={() =>
                router.push({
                  pathname: "/(drawer)/self-driving",
                  params: { report: item.id },
                })
              }
            />
          )
        }
        contentContainerStyle={{
          paddingTop: top,
          paddingBottom: insets.bottom + 140,
          paddingHorizontal: 18,
        }}
        onEndReached={() => {
          if (scope !== "reports" && tasks.hasNextPage && !tasks.isFetching) {
            void tasks.fetchNextPage();
          }
        }}
        onEndReachedThreshold={0.5}
        ListFooterComponent={
          tasks.isFetchingNextPage ? <RowSkeletons count={2} /> : null
        }
        keyboardDismissMode="on-drag"
        keyboardShouldPersistTaps="handled"
      />
      {loading && items.length === 0 ? (
        <View style={[styles.overlay, { top }]} pointerEvents="none">
          <RowSkeletons />
        </View>
      ) : null}
      {!loading && items.length === 0 ? (
        <Text style={[styles.empty, { top: top + 12 }]}>
          {search ? `Nothing matches “${search}”` : "Nothing here yet"}
        </Text>
      ) : null}
      <FadeScrim
        style={[styles.topScrim, { height: top + 8 }]}
        color={colors.bg}
      />
      {searching ? null : (
        <Animated.View
          entering={FadeIn.duration(220)}
          exiting={FadeOut.duration(160)}
          style={[styles.header, { paddingTop: insets.top + 6 }]}
          pointerEvents="box-none"
        >
          <GlassCircleButton onPress={() => navigation.openDrawer()}>
            <MenuIcon />
          </GlassCircleButton>
          <Text style={styles.title}>Search</Text>
          <Host matchContents>
            <Menu
              label={
                <Image
                  systemName="slider.horizontal.3"
                  size={18}
                  color={colors.ink}
                />
              }
              modifiers={[
                frame({ width: 46, height: 46 }),
                glassEffect({
                  glass: { variant: "regular", interactive: true },
                  shape: "circle",
                }),
              ]}
            >
              {SCOPES.map((option) => (
                <Button
                  key={option.value}
                  label={option.label}
                  systemImage={
                    scope === option.value ? "checkmark" : option.icon
                  }
                  onPress={() => setScope(option.value)}
                />
              ))}
            </Menu>
          </Host>
        </Animated.View>
      )}
      <KeyboardStickyView
        style={styles.dock}
        offset={{ closed: 0, opened: insets.bottom }}
      >
        <FadeScrim style={styles.bottomScrim} color={colors.bg} />
        <View style={{ paddingBottom: insets.bottom + 8 }}>
          {searching ? null : (
            <Animated.View
              entering={FadeInDown.duration(240)}
              exiting={FadeOutDown.duration(160)}
              style={styles.newTaskWrap}
            >
              <Pressable
                onPress={() => router.replace("/(drawer)")}
                style={({ pressed }) => [
                  styles.newTask,
                  pressed && { opacity: 0.8 },
                ]}
              >
                <Text style={styles.newTaskPlus}>+</Text>
                <Text style={styles.newTaskText}>New task</Text>
              </Pressable>
            </Animated.View>
          )}
          <View style={styles.searchRow}>
            <Animated.View
              layout={LinearTransition.duration(220)}
              style={styles.searchFlex}
            >
              <Glass interactive style={styles.searchBar}>
                <Host matchContents>
                  <Image
                    systemName="magnifyingglass"
                    size={17}
                    color={colors.inkSoft}
                  />
                </Host>
                <TextInput
                  ref={input}
                  value={query}
                  onChangeText={setQuery}
                  onFocus={() => setSearching(true)}
                  placeholder="Search"
                  placeholderTextColor={colors.inkMute}
                  autoFocus
                  autoCorrect={false}
                  returnKeyType="search"
                  clearButtonMode="while-editing"
                  style={styles.searchInput}
                />
              </Glass>
            </Animated.View>
            {searching ? (
              <Animated.View
                entering={ZoomIn.duration(200)}
                exiting={ZoomOut.duration(160)}
              >
                <GlassCircleButton size={50} onPress={closeSearch}>
                  <Host matchContents>
                    <Image systemName="xmark" size={18} color={colors.ink} />
                  </Host>
                </GlassCircleButton>
              </Animated.View>
            ) : null}
          </View>
        </View>
      </KeyboardStickyView>
    </DrawerScene>
  );
}

const styles = StyleSheet.create({
  header: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 16,
  },
  title: {
    flex: 1,
    fontFamily: fonts.sansBold,
    fontSize: 26,
    color: colors.ink,
  },
  topScrim: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    transform: [{ rotate: "180deg" }],
  },
  overlay: { position: "absolute", left: 18, right: 18 },
  empty: {
    position: "absolute",
    left: 22,
    right: 22,
    fontFamily: fonts.sans,
    fontSize: 15,
    color: colors.inkMute,
  },
  dock: { position: "absolute", left: 0, right: 0, bottom: 0 },
  bottomScrim: { position: "absolute", left: 0, right: 0, top: -24, bottom: 0 },
  searchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 16,
  },
  searchFlex: { flex: 1 },
  searchBar: {
    height: 50,
    borderRadius: radius.pill,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 18,
  },
  searchInput: {
    flex: 1,
    height: "100%",
    fontFamily: fonts.sans,
    fontSize: 17,
    color: colors.ink,
  },
  newTaskWrap: { alignSelf: "flex-end", marginRight: 16, marginBottom: 12 },
  newTask: {
    height: 52,
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
