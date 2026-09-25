import { FlashList, type FlashListRef } from "@shopify/flash-list";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { KeyboardAvoidingView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatHeader } from "@/components/ChatHeader";
import { Composer } from "@/components/Composer";
import { DrawerScene } from "@/components/DrawerScene";
import { Hedgehog } from "@/components/Hedgehog";
import {
  buildTranscriptRows,
  StatusLine,
  type TranscriptRow,
  TranscriptRowView,
} from "@/components/Transcript";
import { useComposer } from "@/lib/composer";
import type { PendingPhoto } from "@/lib/photos";
import { usePrefs } from "@/lib/prefs";
import { useTask } from "@/lib/queries";
import { useSessions } from "@/lib/session";
import { colors, fonts } from "@/lib/theme";

export default function TaskScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  // Placeholder chats have no task yet; the store holds their session.
  const isPending = id.startsWith("new-");
  const task = useTask(isPending ? "" : id);
  const session = useSessions((s) => s.sessions[id]);
  const hedgehogMode = usePrefs((s) => s.hedgehogMode);
  const { connect, disconnect, sendPrompt, cancelTurn, respondToPermission } =
    useSessions();
  const setModel = useComposer((s) => s.setModel);
  const listRef = useRef<FlashListRef<TranscriptRow>>(null);
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const followNextMessage = useRef(false);

  const runId = task.data?.latest_run?.id;
  useEffect(() => {
    if (task.data && runId) connect(task.data);
  }, [task.data, runId, connect]);

  useEffect(() => () => disconnect(id), [id, disconnect]);

  useEffect(() => {
    const runModel = task.data?.latest_run?.model;
    if (runModel) setModel(runModel);
  }, [task.data?.latest_run?.model, setModel]);

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
      <ChatHeader inline />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior="padding">
        <View style={{ flex: 1 }}>
          <FlashList
            ref={listRef}
            data={rows}
            keyExtractor={(row) => row.id}
            getItemType={(row) => row.kind}
            renderItem={({ item }) => (
              <TranscriptRowView
                row={item}
                onPermission={(toolCallId, optionId) =>
                  respondToPermission(id, toolCallId, optionId)
                }
              />
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
              startRenderingFromBottom: true,
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
              session?.error ? (
                <Text style={styles.error}>{session.error}</Text>
              ) : null
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
          {session && hedgehogMode ? <Hedgehog walking={walking} /> : null}
          <View>
            <Composer
              placeholder="Reply"
              onSend={send}
              onStop={isPending ? undefined : () => cancelTurn(id)}
              busy={session?.turnActive}
              sending={isPending}
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
    backgroundColor: colors.bg,
  },
});
