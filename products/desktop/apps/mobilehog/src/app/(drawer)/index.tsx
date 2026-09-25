import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import {
  KeyboardStickyView,
  useReanimatedKeyboardAnimation,
} from "react-native-keyboard-controller";
import Animated, { useAnimatedStyle } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatHeader } from "@/components/ChatHeader";
import { Composer } from "@/components/Composer";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { DrawerScene } from "@/components/DrawerScene";
import { Logomark } from "@/components/Icons";
import { sessionIdentity, useAuth } from "@/lib/auth";
import { buildPhotoPrompt, type PendingPhoto } from "@/lib/photos";
import {
  createAndRunTask,
  useDefaultRepository,
  useInvalidateTasks,
} from "@/lib/queries";
import { colors, fonts } from "@/lib/theme";

export default function NewChatScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const userName = useAuth((s) => s.session?.userName ?? "");
  const repository = useDefaultRepository();
  const submitting = useRef(false);
  const [sending, setSending] = useState(false);
  const invalidateTasks = useInvalidateTasks();
  // Keep the greeting centred in the space the keyboard leaves. The reported
  // height covers the bottom inset too, which the composer already occupied.
  const keyboard = useReanimatedKeyboardAnimation();
  const bottomInset = insets.bottom;
  const hero = useAnimatedStyle(() => ({
    transform: [
      {
        translateY: Math.min(0, keyboard.height.value + bottomInset) / 2,
      },
    ],
  }));

  const send = async (
    text: string,
    photos: PendingPhoto[],
    draft: { taskId?: string; saveTaskId: (id: string) => Promise<void> },
  ): Promise<void> => {
    if (submitting.current) return;
    submitting.current = true;
    setSending(true);
    const identity = sessionIdentity();
    try {
      const wirePrompt = await buildPhotoPrompt(text, photos);
      if (sessionIdentity() !== identity)
        throw new Error("Session changed. Sign in again.");
      const task = await createAndRunTask({
        prompt: text || "Please look at the attached image.",
        wirePrompt,
        repository: repository.data ?? null,
        taskId: draft.taskId,
        onCreated: draft.saveTaskId,
      });
      if (sessionIdentity() !== identity)
        throw new Error("Session changed. Sign in again.");
      invalidateTasks();
      router.replace({
        pathname: "/(drawer)/task/[id]",
        params: { id: task.id },
      });
    } finally {
      submitting.current = false;
      setSending(false);
    }
  };

  return (
    <DrawerScene>
      <ChatHeader inline />
      <ConnectionBanner />
      <Animated.View style={[styles.center, hero]}>
        <Logomark />
        <Text style={styles.greeting}>
          {userName ? `${userName} returns!` : "G'day"}
        </Text>
      </Animated.View>
      <KeyboardStickyView offset={{ closed: 0, opened: insets.bottom }}>
        <View style={[styles.composer, { paddingBottom: insets.bottom + 8 }]}>
          <Composer
            draftId="new"
            placeholder="Chat with PostHog"
            repository={repository.data ?? null}
            sending={sending}
            onSend={send}
            autoFocus
          />
        </View>
      </KeyboardStickyView>
    </DrawerScene>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingHorizontal: 32,
  },
  greeting: {
    fontFamily: fonts.serif,
    fontSize: 30,
    color: colors.ink,
    textAlign: "center",
  },
  composer: { paddingHorizontal: 12 },
});
