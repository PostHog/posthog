import { useLocalSearchParams } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import { KeyboardStickyView } from "react-native-keyboard-controller";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatHeader } from "@/components/ChatHeader";
import { Composer } from "@/components/Composer";
import { DrawerScene } from "@/components/DrawerScene";
import { FadeScrim } from "@/components/FadeScrim";
import { Hedgehog } from "@/components/Hedgehog";
import { StatusLine, Transcript } from "@/components/Transcript";
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
  const scrollRef = useRef<ScrollView>(null);
  // The transcript replays in batches, so follow the bottom as content grows
  // until the reader scrolls or sends; from then on they own the position.
  const followBottom = useRef(true);
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

  const send = async (text: string): Promise<void> => {
    // The bubble lays out before the request resolves, so pick the id first.
    const blockId = `local-${Date.now()}`;
    pendingScrollTo.current = blockId;
    followBottom.current = false;
    setPinRoom(true);
    await sendPrompt(id, text, blockId);
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

  return (
    <DrawerScene>
      <ChatHeader />
      <ScrollView
        ref={scrollRef}
        onLayout={(event) => setViewportHeight(event.nativeEvent.layout.height)}
        contentContainerStyle={[
          styles.scroll,
          {
            paddingTop: topPadding,
            // Clear the floating composer, and leave room to pin a fresh
            // message near the top of the screen.
            paddingBottom: pinRoom
              ? Math.max(composerHeight + 16, viewportHeight - 200)
              : composerHeight + 16,
          },
        ]}
        keyboardDismissMode="interactive"
        onScrollBeginDrag={() => {
          followBottom.current = false;
        }}
        onContentSizeChange={() => {
          if (followBottom.current) {
            scrollRef.current?.scrollToEnd({ animated: false });
          }
        }}
      >
        {session ? (
          <Transcript
            session={session}
            workingLabel={
              session.resuming
                ? "Reconnecting"
                : booting
                  ? "Starting sandbox"
                  : session.connected
                    ? "Working"
                    : "Connecting"
            }
            onPermission={(toolCallId, optionId) =>
              respondToPermission(id, toolCallId, optionId)
            }
            onUserLayout={onUserLayout}
          />
        ) : (
          <View style={styles.loading}>
            <StatusLine
              label={task.error ? task.error.message : "Loading"}
              active={!task.error}
            />
          </View>
        )}
        {session?.error ? (
          <Text style={styles.error}>{session.error}</Text>
        ) : null}
      </ScrollView>
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

const styles = StyleSheet.create({
  loading: { paddingHorizontal: 18 },
  scroll: { gap: 14 },
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
