import { DEFAULT_GATEWAY_MODEL } from "@posthog/shared";
import { FlashList, type FlashListRef } from "@shopify/flash-list";
import { useFocusEffect, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatHeader } from "@/components/ChatHeader";
import { Composer } from "@/components/Composer";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { DrawerScene } from "@/components/DrawerScene";
import { Hedgehog } from "@/components/Hedgehog";
import { TaskActions } from "@/components/TaskActions";
import {
  buildTranscriptRows,
  StatusLine,
  type TranscriptRow,
  TranscriptRowView,
} from "@/components/Transcript";
import type { PendingPhoto } from "@/lib/photos";
import { usePrefs } from "@/lib/prefs";
import { useTask } from "@/lib/queries";
import { useSessions } from "@/lib/session";
import { colors, fonts } from "@/lib/theme";

export default function TaskScreen() {
  const { id, archived, search } = useLocalSearchParams<{
    id: string;
    archived?: string;
    search?: string;
  }>();
  const insets = useSafeAreaInsets();
  // Placeholder chats have no task yet; the store holds their session.
  const isPending = id.startsWith("new-");
  const task = useTask(isPending ? "" : id);
  const session = useSessions((s) => s.sessions[id]);
  const hedgehogMode = usePrefs((s) => s.hedgehogMode);
  const { connect, disconnect, sendPrompt, cancelTurn, respondToPermission } =
    useSessions();
  const listRef = useRef<FlashListRef<TranscriptRow>>(null);
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const followNextMessage = useRef(false);

  const runId = task.data?.latest_run?.id;
  useFocusEffect(
    useCallback(() => {
      if (task.data && runId) connect(task.data);
      return () => disconnect(id);
    }, [id, task.data, runId, connect, disconnect]),
  );

  const blocks = session?.blocks;
  // Walks while thinking or using tools; stands still once text is streaming.
  const tail = blocks?.[blocks.length - 1];
  const streamingText = tail?.kind === "agent" && !tail.complete;
  const walking = !!session?.turnActive && !streamingText;
  const booting =
    !!session &&
    (session.runStatus === "queued" || session.runStatus === "not_started") &&
    !blocks?.some((block) => block.kind !== "user");

  const workingLabel = session?.resuming
    ? "Reconnecting"
    : booting
      ? "Starting sandbox"
      : session?.connected
        ? "Working"
        : "Connecting";
  const rows = useMemo(
    () => (session ? buildTranscriptRows(session, workingLabel) : []),
    [session, workingLabel],
  );

  const matches = useMemo(
    () =>
      search
        ? rows.flatMap((row, index) =>
            row.kind === "block" &&
            "text" in row.block &&
            row.block.text.toLowerCase().includes(search.toLowerCase())
              ? [index]
              : [],
          )
        : [],
    [rows, search],
  );
  const [match, setMatch] = useState(0);
  const lastSearch = useRef("");
  useEffect(() => {
    if (search && matches.length && lastSearch.current !== `${id}:${search}`) {
      lastSearch.current = `${id}:${search}`;
      setMatch(0);
      requestAnimationFrame(() =>
        listRef.current?.scrollToIndex({ index: matches[0], animated: false }),
      );
    }
  }, [id, search, matches]);

  const send = async (text: string, photos: PendingPhoto[]): Promise<void> => {
    followNextMessage.current = true;
    await sendPrompt(id, text, `local-${Date.now()}`, photos);
  };

  const scrollToLatest = (): void => {
    listRef.current?.scrollToEnd({ animated: true });
    setAwayFromBottom(false);
  };

  return (
    <DrawerScene>
      <ChatHeader
        inline
        actions={
          task.data ? (
            <TaskActions task={task.data} archived={archived === "true"} />
          ) : undefined
        }
      />
      <ConnectionBanner />
      {search ? (
        <View style={{ padding: 12, flexDirection: "row", gap: 12 }}>
          <Text style={{ color: colors.ink, flex: 1 }}>
            {matches.length
              ? `${match + 1} of ${matches.length} matches`
              : "No saved matches"}
          </Text>
          <Pressable
            accessibilityRole="button"
            disabled={!matches.length}
            style={{ minHeight: 44 }}
            onPress={() => {
              const next = (match + 1) % matches.length;
              setMatch(next);
              listRef.current?.scrollToIndex({
                index: matches[next],
                animated: true,
              });
            }}
          >
            <Text style={{ color: colors.accent }}>Next match</Text>
          </Pressable>
        </View>
      ) : null}
      <KeyboardAvoidingView style={{ flex: 1 }} behavior="padding">
        <View style={{ flex: 1 }}>
          <FlashList
            ref={listRef}
            data={rows}
            keyExtractor={(row) => row.id}
            getItemType={(row) => row.kind}
            renderItem={({ item }) => (
              <View
                style={
                  search &&
                  item.kind === "block" &&
                  "text" in item.block &&
                  item.block.text.toLowerCase().includes(search.toLowerCase())
                    ? {
                        borderLeftWidth: 3,
                        borderLeftColor: colors.accent,
                        paddingLeft: 8,
                      }
                    : undefined
                }
              >
                <TranscriptRowView
                  row={item}
                  onPermission={(toolCallId, optionId) =>
                    respondToPermission(id, toolCallId, optionId)
                  }
                />
              </View>
            )}
            ItemSeparatorComponent={Gap}
            onScroll={({ nativeEvent }) => {
              const distance =
                nativeEvent.contentSize.height -
                nativeEvent.layoutMeasurement.height -
                nativeEvent.contentOffset.y;
              setAwayFromBottom(distance > 100);
            }}
            scrollEventThrottle={100}
            onContentSizeChange={() => {
              if (followNextMessage.current) {
                followNextMessage.current = false;
                scrollToLatest();
              }
            }}
            contentContainerStyle={{
              paddingTop: 8,
              paddingHorizontal: 18,
              paddingBottom: 16,
            }}
            maintainVisibleContentPosition={{
              startRenderingFromBottom: !search,
              autoscrollToBottomThreshold: 0.2,
              animateAutoScrollToBottom: false,
            }}
            keyboardDismissMode="interactive"
            keyboardShouldPersistTaps="handled"
            ListEmptyComponent={
              <View style={styles.loading}>
                <StatusLine
                  label={task.error ? task.error.message : "Loading"}
                  active={!task.error}
                />
              </View>
            }
            ListFooterComponent={
              <View>
                {session?.error ? (
                  <Text style={styles.error}>{session.error}</Text>
                ) : null}
                {session?.turnActive && hedgehogMode ? (
                  <Hedgehog walking={walking} />
                ) : null}
              </View>
            }
          />
          {awayFromBottom ? (
            <Pressable
              style={styles.latest}
              accessibilityRole="button"
              onPress={scrollToLatest}
            >
              <Text style={styles.latestText}>↓ Latest message</Text>
            </Pressable>
          ) : null}
        </View>
        <View style={[styles.composer, { paddingBottom: insets.bottom + 8 }]}>
          <View>
            <Composer
              key={id}
              draftId={id}
              initialModel={
                task.data
                  ? (task.data.latest_run?.model ??
                    (task.isPlaceholderData
                      ? undefined
                      : DEFAULT_GATEWAY_MODEL))
                  : undefined
              }
              initialReasoning={
                task.data?.latest_run?.reasoning_effort ?? undefined
              }
              placeholder="Reply"
              onSend={send}
              onStop={isPending ? undefined : () => cancelTurn(id)}
              busy={session?.turnActive}
              sending={isPending}
              disabled={!session?.runId || !task.data || task.isPlaceholderData}
            />
          </View>
        </View>
      </KeyboardAvoidingView>
    </DrawerScene>
  );
}

function Gap() {
  return <View style={styles.gap} />;
}

const styles = StyleSheet.create({
  loading: { paddingTop: 4 },
  gap: { height: 14 },
  error: {
    color: colors.danger,
    fontFamily: fonts.sans,
    fontSize: 13,
    paddingHorizontal: 18,
    marginTop: 8,
  },
  latest: {
    alignSelf: "center",
    padding: 10,
    marginBottom: 8,
    borderRadius: 20,
    backgroundColor: colors.surface,
  },
  latestText: { fontFamily: fonts.sansMedium, color: colors.ink, fontSize: 14 },
  composer: {
    paddingHorizontal: 12,
    paddingTop: 8,
  },
});
