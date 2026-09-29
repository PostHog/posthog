import { useLocalSearchParams } from "expo-router";
import { useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { KeyboardStickyView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatHeader } from "@/components/ChatHeader";
import { Composer } from "@/components/Composer";
import { DrawerScene } from "@/components/DrawerScene";
import { Transcript } from "@/components/Transcript";
import { DEFAULT_MODEL } from "@/config";
import { useTask } from "@/lib/queries";
import { useSessions } from "@/lib/session";
import { colors } from "@/lib/theme";

function statusLine(
  runStatus: string | null,
  stage: string | null,
  turnActive: boolean,
  awaitingInput: boolean,
  connected: boolean,
): string {
  if (runStatus === "queued" || runStatus === "not_started")
    return "Starting sandbox";
  if (runStatus === "completed") return "Run finished";
  if (runStatus === "failed") return "Run failed";
  if (runStatus === "cancelled") return "Run stopped";
  if (awaitingInput) return "Waiting for you";
  if (turnActive) return stage ? stage : "Working";
  if (!connected) return "Connecting";
  return "Idle";
}

export default function TaskScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const task = useTask(id);
  const session = useSessions((s) => s.sessions[id]);
  const { connect, disconnect, sendPrompt, cancelTurn, respondToPermission } =
    useSessions();
  const [model, setModel] = useState(
    task.data?.latest_run?.model ?? DEFAULT_MODEL,
  );
  const scrollRef = useRef<ScrollView>(null);
  // Follow the bottom only until the first transcript paints; after that the
  // reader owns the scroll position, except when they send a message.
  const didInitialScroll = useRef(false);
  const pendingScrollTo = useRef<string | null>(null);
  const [viewportHeight, setViewportHeight] = useState(0);
  const topPadding = insets.top + 70;

  const runId = task.data?.latest_run?.id;
  useEffect(() => {
    if (task.data && runId) connect(task.data);
  }, [task.data, runId, connect]);

  useEffect(() => () => disconnect(id), [id, disconnect]);

  useEffect(() => {
    const runModel = task.data?.latest_run?.model;
    if (runModel) setModel(runModel);
  }, [task.data?.latest_run?.model]);

  const blocks = session?.blocks;
  useEffect(() => {
    if (blocks && blocks.length > 0 && !didInitialScroll.current) {
      didInitialScroll.current = true;
      requestAnimationFrame(() =>
        scrollRef.current?.scrollToEnd({ animated: false }),
      );
    }
  }, [blocks]);

  const send = async (text: string): Promise<void> => {
    // The bubble lays out before the request resolves, so pick the id first.
    const blockId = `local-${Date.now()}`;
    pendingScrollTo.current = blockId;
    await sendPrompt(id, text, model, blockId);
  };

  // Keep a sliver of the previous reply above the new message. Anything
  // taller than the viewport starts at its top so as much as possible shows.
  const onUserLayout = (blockId: string, y: number): void => {
    if (pendingScrollTo.current !== blockId) return;
    pendingScrollTo.current = null;
    scrollRef.current?.scrollTo({
      y: Math.max(0, topPadding + y - 56),
      animated: true,
    });
  };

  const subtitle = session
    ? statusLine(
        session.runStatus,
        session.stage,
        session.turnActive,
        session.awaitingInput,
        session.connected,
      )
    : "Loading";

  return (
    <DrawerScene>
      <ChatHeader />
      {!session || (session.blocks.length === 0 && !session.connected) ? (
        <View style={styles.loading}>
          <ActivityIndicator color={colors.inkMute} />
          <Text style={styles.loadingText}>
            {task.error ? task.error.message : subtitle}
          </Text>
        </View>
      ) : (
        <ScrollView
          ref={scrollRef}
          onLayout={(event) =>
            setViewportHeight(event.nativeEvent.layout.height)
          }
          contentContainerStyle={[
            styles.scroll,
            {
              paddingTop: topPadding,
              // Room to pin a fresh message near the top of the screen.
              paddingBottom: Math.max(24, viewportHeight - 200),
            },
          ]}
          keyboardDismissMode="interactive"
        >
          <Transcript
            session={session}
            onPermission={(toolCallId, optionId) =>
              respondToPermission(id, toolCallId, optionId)
            }
            onUserLayout={onUserLayout}
          />
          {session.error ? (
            <Text style={styles.error}>{session.error}</Text>
          ) : null}
        </ScrollView>
      )}
      <KeyboardStickyView offset={{ closed: 0, opened: insets.bottom }}>
        <View style={[styles.composer, { paddingBottom: insets.bottom + 8 }]}>
          <Composer
            placeholder="Reply"
            model={model}
            onModelChange={setModel}
            onSend={send}
            onStop={() => cancelTurn(id)}
            busy={session?.turnActive}
          />
        </View>
      </KeyboardStickyView>
    </DrawerScene>
  );
}

const styles = StyleSheet.create({
  loading: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10 },
  loadingText: { color: colors.inkMute, fontSize: 13 },
  scroll: { gap: 14 },
  error: {
    color: colors.danger,
    fontSize: 13,
    paddingHorizontal: 18,
    marginTop: 8,
  },
  composer: { paddingHorizontal: 12 },
});
