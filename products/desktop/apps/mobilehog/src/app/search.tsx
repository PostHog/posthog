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
import { accountStorageKey, sessionIdentity, useAuth } from "@/lib/auth";
import { useTasks } from "@/lib/queries";
import { colors, fonts, radius } from "@/lib/theme";

const RECENT_SEARCHES_KEY = "mobilehog_recent_searches";

export default function SearchScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const session = useAuth((state) => state.session);
  const identity = sessionIdentity();

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
  const tasks = useTasks(search, !!search);
  const waiting = query.trim() !== search;
  const loading = !!query.trim() && (waiting || tasks.isLoading);

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
        <Text style={styles.caption}>Search your tasks</Text>
      </View>
      <FlatList
        data={waiting || !query.trim() ? [] : tasks.data}
        keyExtractor={(task) => task.id}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        contentContainerStyle={styles.results}
        renderItem={({ item }) => (
          <TaskListRow
            task={item}
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
          !!query.trim() &&
          tasks.isError &&
          tasks.data.length > 0 &&
          !waiting ? (
            <Pressable
              accessibilityRole="button"
              disabled={tasks.isFetching}
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
                description="Search for a task to get started."
                icon={<SearchIcon />}
              />
            )
          ) : loading ? (
            <ListState title="Searching" loading />
          ) : tasks.isError ? (
            <ListState
              title="Could not load tasks"
              description="Check your connection and try again."
              action={{
                label: "Retry",
                onPress: () => void tasks.refetch(),
                disabled: tasks.isFetching,
              }}
            />
          ) : tasks.hasNextPage ? (
            <ListState
              title="No cloud tasks in this page"
              description="Load more tasks to continue."
              icon={<SearchIcon />}
            />
          ) : (
            <ListState
              title="No matching tasks"
              description="Try another title, description, or task number."
              icon={<SearchIcon />}
            />
          )
        }
        ListFooterComponent={
          !!query.trim() && tasks.hasNextPage && !waiting ? (
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
          ) : null
        }
      />
      <View style={[styles.searchBar, { paddingBottom: insets.bottom + 8 }]}>
        <Glass style={styles.inputShell}>
          <SearchIcon color={colors.inkSoft} />
          <TextInput
            accessibilityLabel="Search your tasks"
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
