import { FlashList, type FlashListRef } from "@shopify/flash-list";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { KeyboardStickyView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatHeader } from "@/components/ChatHeader";
import { Composer } from "@/components/Composer";
import { DrawerScene } from "@/components/DrawerScene";
import { FadeScrim } from "@/components/FadeScrim";
import { Hedgehog } from "@/components/Hedgehog";
import {
  buildTranscriptRows,
  StatusLine,
  type TranscriptRow,
  TranscriptRowView,
} from "@/components/Transcript";
import { useComposer } from "@/lib/composer";
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
  const pendingScrollTo = useRef<string | null>(null);
  const [viewportHeight, setViewportHeight] = useState(0);
  const [composerHeight, setComposerHeight] = useState(0);
  // Extra room below the transcript only while a sent message is pinned near
  // the top; it goes away once the reply lands so idle chats have no gap.
  const [pinRoom, setPinRoom] = useState(false);
  const topPadding = insets.top + 70;

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

  const turnActive = !!session?.turnActive;
  useEffect(() => {
    if (!turnActive) setPinRoom(false);
  }, [turnActive]);

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

  const send = async (text: string): Promise<void> => {
    // The bubble lays out before the request resolves, so pick the id first.
    const blockId = `local-${Date.now()}`;
    pendingScrollTo.current = blockId;
    setPinRoom(true);
    await sendPrompt(id, text, blockId);
  };

  // Once the sent bubble is a row, pin it near the top with a sliver of the
  // previous reply above it.
  useEffect(() => {
    const target = pendingScrollTo.current;
    if (!target) return;
    const index = rows.findIndex((row) => row.id === target);
    if (index < 0) return;
    pendingScrollTo.current = null;
    listRef.current?.scrollToIndex({
      index,
      viewPosition: 0,
      viewOffset: 56,
      animated: true,
    });
  }, [rows]);

  return (
    <DrawerScene>
      <ChatHeader />
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
        onLayout={(event) => setViewportHeight(event.nativeEvent.layout.height)}
        contentContainerStyle={{
          paddingTop: topPadding,
          paddingHorizontal: 18,
          // Clear the floating composer, and leave room to pin a fresh
          // message near the top of the screen.
          paddingBottom: pinRoom
            ? Math.max(composerHeight + 16, viewportHeight - 200)
            : composerHeight + 16,
        }}
        // Open at the end, and keep following it while the reader is near the
        // bottom; a pinned message sits far enough up to opt out on its own.
        maintainVisibleContentPosition={{
          startRenderingFromBottom: true,
          autoscrollToBottomThreshold: 0.2,
          animateAutoScrollToBottom: false,
        }}
        keyboardDismissMode="interactive"
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
      <KeyboardStickyView
        offset={{ closed: 0, opened: insets.bottom }}
        style={styles.dock}
      >
        <View
          style={[styles.composer, { paddingBottom: insets.bottom + 8 }]}
          onLayout={(event) =>
            setComposerHeight(event.nativeEvent.layout.height)
          }
        >
          {session && hedgehogMode ? <Hedgehog walking={walking} /> : null}
          <View>
            <FadeScrim style={styles.scrim} />
            <Composer
              placeholder="Reply"
              onSend={send}
              onStop={isPending ? undefined : () => cancelTurn(id)}
              busy={session?.turnActive}
              sending={isPending}
            />
          </View>
        </View>
      </KeyboardStickyView>
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
  dock: { position: "absolute", left: 0, right: 0, bottom: 0 },
  scrim: {
    position: "absolute",
    top: -40,
    bottom: -60,
    left: -12,
    right: -12,
  },
  composer: { paddingHorizontal: 12 },
});
