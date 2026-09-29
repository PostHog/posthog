import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";
import { useEffect, useState } from "react";
import {
  FlatList,
  Keyboard,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass, GlassCircleButton } from "@/components/Glass";
import { SearchIcon } from "@/components/Icons";
import { ListState } from "@/components/ListState";
import { TaskListRow } from "@/components/TaskListRow";
import { useActivity } from "@/lib/activity";
import { accountStorageKey, sessionIdentity, useAuth } from "@/lib/auth";
import { getClient } from "@/lib/client";
import { useTasks } from "@/lib/queries";
import { colors, fonts, radius } from "@/lib/theme";

const RECENT_SEARCHES_KEY = "mobilehog_recent_searches";

export default function SearchScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const insets = useSafeAreaInsets();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const session = useAuth((state) => state.session);
  const identity = sessionIdentity();
  const activity = useActivity().data;
  const unreadTasks = new Set(
    activity?.results.filter((row) => row.is_unread).map((row) => row.task_id),
  );

  useEffect(() => {
    if (!session) return;
    let active = true;
    setRecentSearches([]);
    SecureStore.getItemAsync(accountStorageKey(RECENT_SEARCHES_KEY))
      .then((raw) => {
        if (active && sessionIdentity() === identity)
          setRecentSearches(raw ? (JSON.parse(raw) as string[]) : []);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [identity, session]);

  const saveSearch = (value: string): void => {
    const term = value.trim();
    if (!term || !session) return;
    const next = [
      term,
      ...recentSearches.filter(
        (item) => item.toLowerCase() !== term.toLowerCase(),
      ),
    ].slice(0, 8);
    setRecentSearches(next);
    SecureStore.setItemAsync(
      accountStorageKey(RECENT_SEARCHES_KEY),
      JSON.stringify(next),
    ).catch(() => {});
  };
  useEffect(() => {
    const timeout = setTimeout(() => setSearch(query.trim()), 300);
    return () => clearTimeout(timeout);
  }, [query]);
  const [scope, setScope] = useState<"tasks" | "reports">("tasks");
  const tasks = useTasks(search, !!search && scope === "tasks");
  const reports = useInfiniteQuery({
    queryKey: ["reports", "search", search],
    initialPageParam: 0,
    enabled: !!search && scope === "reports",
    queryFn: async ({ pageParam }) => {
      const client = getClient();
      const user = await queryClient.fetchQuery({
        queryKey: ["current-user"],
        queryFn: async () => ({ uuid: (await client.getCurrentUser()).uuid }),
        staleTime: 5 * 60_000,
      });
      if (!user.uuid) throw new Error("Could not identify your account.");
      return client.getSignalReports({
        search,
        suggested_reviewers: user.uuid,
        status: "ready,pending_input,in_progress,suppressed,resolved,failed",
        limit: 50,
        offset: pageParam,
        ordering: "-updated_at,-id",
      });
    },
    getNextPageParam: (page, pages) => {
      const loaded = pages.reduce((sum, item) => sum + item.results.length, 0);
      return loaded < page.count && page.results.length ? loaded : undefined;
    },
  });
  const activeQuery = scope === "reports" ? reports : tasks;
  const waiting = query.trim() !== search;
  const loading = !!query.trim() && (waiting || activeQuery.isLoading);

  const close = (): void => {
    Keyboard.dismiss();
    if (router.canGoBack()) router.back();
    else router.replace("/(drawer)");
  };

  return (
    <KeyboardAvoidingView
      behavior="padding"
      style={[styles.root, { paddingTop: insets.top + 16 }]}
    >
      <View style={styles.header}>
        <Text style={styles.heading}>
          {query.trim() ? "Search results" : "Recent searches"}
        </Text>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 16 }}>
          {(["tasks", "reports"] as const).map((value) => (
            <Pressable
              key={value}
              accessibilityRole="tab"
              accessibilityState={{ selected: scope === value }}
              style={styles.action}
              onPress={() => setScope(value)}
            >
              <Text
                style={[
                  styles.caption,
                  scope === value && { color: colors.accent },
                ]}
              >
                {value === "reports" ? "Self-driving" : "Tasks"}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>
      <FlatList
        data={waiting || !query.trim() || scope !== "tasks" ? [] : tasks.data}
        keyExtractor={(task) => task.id}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        contentContainerStyle={styles.results}
        renderItem={({ item }) => (
          <TaskListRow
            task={item}
            unread={unreadTasks.has(item.id)}
            preview={!!search}
            onPress={() => {
              saveSearch(query);
              Keyboard.dismiss();
              router.dismissTo({
                pathname: "/(drawer)/task/[id]",
                params: { id: item.id },
              });
            }}
          />
        )}
        ListHeaderComponent={
          scope !== "tasks" && !!query.trim() && !waiting ? (
            <View>
              {(scope === "reports"
                ? (reports.data?.pages.flatMap((page) => page.results) ?? [])
                : []
              ).map((report) => (
                <Pressable
                  key={report.id}
                  accessibilityRole="button"
                  style={styles.recentRow}
                  onPress={() => {
                    saveSearch(query);
                    router.dismissTo({
                      pathname: "/report",
                      params: { id: report.id },
                    });
                  }}
                >
                  <View style={{ flex: 1, gap: 6 }}>
                    <Text style={styles.recentText}>
                      {report.title || "Untitled report"}
                    </Text>
                    <Text style={styles.caption} numberOfLines={2}>
                      {report.summary}
                    </Text>
                  </View>
                </Pressable>
              ))}
            </View>
          ) : !!query.trim() &&
            tasks.isError &&
            tasks.data.length > 0 &&
            !waiting ? (
            <Pressable
              accessibilityRole="button"
              disabled={activeQuery.isFetching}
              onPress={() => void tasks.refetch()}
              style={styles.action}
            >
              <Text style={styles.actionText}>
                Could not update results. Tap to retry.
              </Text>
            </Pressable>
          ) : null
        }
        ListEmptyComponent={
          !query.trim() ? (
            recentSearches.length ? (
              <View style={styles.recent}>
                {recentSearches.map((term) => (
                  <Pressable
                    key={term}
                    accessibilityRole="button"
                    onPress={() => {
                      setQuery(term);
                      setSearch(term);
                      saveSearch(term);
                    }}
                    style={styles.recentRow}
                  >
                    <SearchIcon color={colors.inkSoft} />
                    <Text style={styles.recentText} numberOfLines={1}>
                      {term}
                    </Text>
                  </Pressable>
                ))}
              </View>
            ) : (
              <ListState
                title="No recent searches"
                description="Search Tasks or Self-driving to get started."
                icon={<SearchIcon />}
              />
            )
          ) : scope === "reports" &&
            reports.data?.pages.some(
              (page) => page.results.length,
            ) ? null : loading ? (
            <ListState title="Searching" loading />
          ) : activeQuery.isError ? (
            <ListState
              title="Could not load results"
              description="Check your connection and try again."
              action={{
                label: "Retry",
                onPress: () => void activeQuery.refetch(),
                disabled: activeQuery.isFetching,
              }}
            />
          ) : activeQuery.hasNextPage ? (
            <ListState
              title="No cloud tasks in this page"
              description="Load more tasks to continue."
              icon={<SearchIcon />}
            />
          ) : (
            <ListState
              title="No matches"
              description="Try another search."
              icon={<SearchIcon />}
            />
          )
        }
        ListFooterComponent={
          !!query.trim() && activeQuery.hasNextPage && !waiting ? (
            <Pressable
              accessibilityRole="button"
              disabled={activeQuery.isFetching}
              onPress={() => void activeQuery.fetchNextPage()}
              style={styles.action}
            >
              <Text style={styles.actionText}>
                {activeQuery.isFetchingNextPage ? "Loading" : "Load more"}
              </Text>
            </Pressable>
          ) : null
        }
      />
      <View style={[styles.searchBar, { paddingBottom: insets.bottom + 8 }]}>
        <Glass style={styles.inputShell}>
          <SearchIcon color={colors.inkSoft} />
          <TextInput
            accessibilityLabel="Search"
            value={query}
            onChangeText={setQuery}
            placeholder="Search"
            placeholderTextColor={colors.inkMute}
            autoFocus
            autoCapitalize="none"
            autoCorrect={false}
            clearButtonMode="while-editing"
            returnKeyType="search"
            onSubmitEditing={() => {
              setSearch(query.trim());
              saveSearch(query);
            }}
            style={styles.input}
          />
        </Glass>
        <GlassCircleButton
          accessibilityLabel="Close search"
          size={50}
          onPress={close}
        >
          <Text style={styles.close}>×</Text>
        </GlassCircleButton>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  header: { paddingHorizontal: 22, paddingBottom: 16, gap: 6 },
  heading: { fontFamily: fonts.sansSemi, fontSize: 22, color: colors.ink },
  caption: { fontFamily: fonts.sans, fontSize: 14, color: colors.inkSoft },
  results: { flexGrow: 1, paddingHorizontal: 18, paddingBottom: 16 },
  recent: { gap: 4 },
  recentRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 14,
    paddingHorizontal: 6,
  },
  recentText: {
    flex: 1,
    fontFamily: fonts.sans,
    fontSize: 16,
    color: colors.ink,
  },
  searchBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 16,
    paddingTop: 8,
  },
  inputShell: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    borderRadius: radius.pill,
    paddingHorizontal: 16,
    overflow: "hidden",
  },
  input: {
    flex: 1,
    minWidth: 0,
    fontFamily: fonts.sans,
    fontSize: 17,
    color: colors.ink,
    paddingVertical: 15,
  },
  close: {
    fontFamily: fonts.sans,
    fontSize: 32,
    lineHeight: 34,
    color: colors.ink,
  },
  action: { paddingVertical: 16, alignItems: "center" },
  actionText: {
    fontFamily: fonts.sansMedium,
    fontSize: 15,
    color: colors.accent,
  },
});
