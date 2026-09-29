import { useRouter } from "expo-router";
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
import { useTasks } from "@/lib/queries";
import { colors, fonts, radius } from "@/lib/theme";

export default function SearchScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timeout = setTimeout(() => setSearch(query.trim()), 300);
    return () => clearTimeout(timeout);
  }, [query]);
  const tasks = useTasks(search);
  const waiting = query.trim() !== search;
  const loading = waiting || tasks.isLoading;

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
          {query.trim() ? "Search results" : "Recent Tasks"}
        </Text>
        <Text style={styles.caption}>Search your tasks</Text>
      </View>
      <FlatList
        data={waiting ? [] : tasks.data}
        keyExtractor={(task) => task.id}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        contentContainerStyle={styles.results}
        renderItem={({ item }) => (
          <TaskListRow
            task={item}
            preview={!!search}
            onPress={() => {
              Keyboard.dismiss();
              router.dismissTo({
                pathname: "/(drawer)/task/[id]",
                params: { id: item.id },
              });
            }}
          />
        )}
        ListHeaderComponent={
          tasks.isError && tasks.data.length > 0 && !waiting ? (
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
          loading ? (
            <ListState
              title={query.trim() ? "Searching" : "Loading tasks"}
              loading
            />
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
              title={search ? "No matching tasks" : "No tasks yet"}
              description={
                search
                  ? "Try another title, description, or task number."
                  : "Your cloud tasks will appear here when you start one."
              }
              icon={<SearchIcon />}
            />
          )
        }
        ListFooterComponent={
          tasks.hasNextPage && !waiting ? (
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
            onSubmitEditing={() => setSearch(query.trim())}
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
