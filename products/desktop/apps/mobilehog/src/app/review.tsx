import { useInfiniteQuery } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useState } from "react";
import {
  FlatList,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { GlassCircleButton } from "@/components/Glass";
import { ListState } from "@/components/ListState";
import { getClient } from "@/lib/client";
import { useTask } from "@/lib/queries";
import { colors, fonts } from "@/lib/theme";

export default function ReviewScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const task = useTask(id);
  const review = useInfiniteQuery({
    queryKey: ["task-review", id],
    initialPageParam: 1,
    queryFn: ({ pageParam }) => getClient().getTaskReview(id, pageParam),
    getNextPageParam: (page, pages) =>
      page.has_more ? pages.length + 1 : undefined,
  });
  const snapshot = review.data?.pages[0];
  const rawUrl = snapshot?.url ?? task.data?.latest_run?.output?.pr_url;
  const url =
    typeof rawUrl === "string" &&
    /^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+\/?$/.test(rawUrl)
      ? rawUrl
      : null;
  const files = review.data?.pages.flatMap((page) => page.files) ?? [];
  const changed = review.data?.pages.some(
    (page) => page.head_sha !== snapshot?.head_sha,
  );
  const reload = (): void => {
    void review.refetch();
  };
  return (
    <View
      style={[
        styles.root,
        { paddingTop: insets.top, paddingBottom: insets.bottom },
      ]}
    >
      <View style={styles.header}>
        <GlassCircleButton
          accessibilityLabel="Close review"
          onPress={() => router.back()}
        >
          <Text style={styles.close}>×</Text>
        </GlassCircleButton>
        <Text style={styles.heading}>Review result</Text>
      </View>
      <FlatList
        data={changed ? [] : files}
        keyExtractor={(file) => file.filename}
        contentContainerStyle={{ padding: 16, gap: 12 }}
        refreshing={review.isRefetching}
        onRefresh={reload}
        ListHeaderComponent={
          <View style={{ gap: 12, paddingBottom: 16 }}>
            <Text style={styles.heading}>
              {snapshot?.title ?? task.data?.title}
            </Text>
            {snapshot ? (
              <Text style={styles.copy}>
                {snapshot.state} · Checks:{" "}
                {snapshot.ci_status === "none"
                  ? "No check result"
                  : snapshot.ci_status}
              </Text>
            ) : null}
            {url ? (
              <Pressable
                accessibilityRole="link"
                onPress={() => void Linking.openURL(url)}
                style={styles.button}
              >
                <Text style={styles.link}>Open in GitHub</Text>
              </Pressable>
            ) : null}
            {review.isError && files.length ? (
              <Text style={styles.copy}>
                Could not refresh this review. Pull to try again.
              </Text>
            ) : null}
          </View>
        }
        ListEmptyComponent={
          <ListState
            loading={review.isLoading}
            title={
              review.isLoading
                ? "Loading review"
                : changed
                  ? "The pull request changed"
                  : review.isError
                    ? "Review unavailable"
                    : "No changed files"
            }
            description={
              changed
                ? "Refresh to load files from the same revision."
                : review.isError
                  ? "The task needs a pull request and a GitHub connection. Open GitHub or try again."
                  : undefined
            }
            action={
              review.isError || changed
                ? { label: "Try again", onPress: reload }
                : undefined
            }
          />
        }
        renderItem={({ item }) => (
          <View style={styles.file}>
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ expanded: expanded.has(item.filename) }}
              onPress={() =>
                setExpanded((previous) => {
                  const next = new Set(previous);
                  if (next.has(item.filename)) next.delete(item.filename);
                  else next.add(item.filename);
                  return next;
                })
              }
              style={styles.button}
            >
              <Text style={styles.filename}>{item.filename}</Text>
              <Text style={styles.copy}>
                {item.status} · +{item.additions} −{item.deletions}
              </Text>
            </Pressable>
            {expanded.has(item.filename) ? (
              <View>
                {item.patch ? (
                  <ScrollView horizontal>
                    <Text selectable style={styles.diff}>
                      {item.patch.split("\n").map((line, index) => (
                        <Text
                          key={`${index}-${line.slice(0, 12)}`}
                          style={{
                            color: line.startsWith("+")
                              ? colors.ok
                              : line.startsWith("-")
                                ? colors.danger
                                : colors.ink,
                          }}
                        >
                          {line}
                          {"\n"}
                        </Text>
                      ))}
                    </Text>
                  </ScrollView>
                ) : null}
                {item.truncated ? (
                  <Text style={styles.copy}>
                    This preview is incomplete. Open GitHub for the full change.
                  </Text>
                ) : null}
              </View>
            ) : null}
          </View>
        )}
        ListFooterComponent={
          review.hasNextPage ? (
            <Pressable
              accessibilityRole="button"
              disabled={review.isFetchingNextPage}
              style={styles.button}
              onPress={() => void review.fetchNextPage()}
            >
              <Text style={styles.link}>
                {review.isFetchingNextPage ? "Loading" : "Load more files"}
              </Text>
            </Pressable>
          ) : null
        }
      />
    </View>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  header: { flexDirection: "row", alignItems: "center", gap: 16, padding: 16 },
  heading: { color: colors.ink, fontSize: 20, fontFamily: fonts.sansSemi },
  close: { color: colors.ink, fontSize: 24 },
  copy: { color: colors.inkSoft, fontSize: 14, fontFamily: fonts.sans },
  link: { color: colors.accent, fontSize: 16, fontFamily: fonts.sansMedium },
  file: { backgroundColor: colors.surface, padding: 12, borderRadius: 12 },
  button: { minHeight: 44, justifyContent: "center", gap: 6 },
  filename: { color: colors.ink, fontSize: 15, fontFamily: fonts.sansMedium },
  diff: {
    fontFamily: fonts.mono,
    fontSize: 12,
    lineHeight: 19,
    paddingVertical: 12,
  },
});
