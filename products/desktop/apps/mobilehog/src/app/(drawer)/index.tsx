import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import {
  KeyboardStickyView,
  useReanimatedKeyboardAnimation,
} from "react-native-keyboard-controller";
import Animated, { useAnimatedStyle } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatHeader } from "@/components/ChatHeader";
import { Composer } from "@/components/Composer";
import { DrawerScene } from "@/components/DrawerScene";
import { Logomark } from "@/components/Icons";
import { useAuth } from "@/lib/auth";
import {
  createAndRunTask,
  useDefaultRepository,
  useInvalidateTasks,
} from "@/lib/queries";
import { useSessions } from "@/lib/session";
import { colors, fonts } from "@/lib/theme";

export default function NewChatScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const userName = useAuth((s) => s.session?.userName ?? "");
  const repository = useDefaultRepository();
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

  // Open the chat immediately with the message in it; the task and its run
  // are created behind that screen, then the chat is re-keyed to the real id.
  const send = async (text: string): Promise<void> => {
    const tempId = `new-${Date.now()}`;
    const { startPending, adopt, failPending } = useSessions.getState();
    startPending(tempId, text, `local-${Date.now()}`);
    router.replace({ pathname: "/(drawer)/task/[id]", params: { id: tempId } });
    try {
      const task = await createAndRunTask({
        prompt: text,
        repository: repository.data ?? null,
      });
      adopt(tempId, task);
      invalidateTasks();
      router.replace({
        pathname: "/(drawer)/task/[id]",
        params: { id: task.id },
      });
    } catch (err) {
      failPending(tempId, err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <DrawerScene>
      <ChatHeader showNewChat={false} />
      <Animated.View style={[styles.center, hero]}>
        <Logomark />
        <Text style={styles.greeting}>
          {userName ? `${userName} returns!` : "G'day"}
        </Text>
      </Animated.View>
      <KeyboardStickyView offset={{ closed: 0, opened: insets.bottom }}>
        <View style={[styles.composer, { paddingBottom: insets.bottom + 8 }]}>
          <Composer
            placeholder="Chat with PostHog"
            repository={repository.data ?? null}
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
