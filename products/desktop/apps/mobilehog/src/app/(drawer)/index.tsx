import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActionSheetIOS,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
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
import { DEFAULT_MODEL } from "@/config";
import { useAuth } from "@/lib/auth";
import {
  createAndRunTask,
  useDefaultRepository,
  useInvalidateTasks,
  useRepositories,
} from "@/lib/queries";
import { useRepo } from "@/lib/repo";
import { colors, fonts } from "@/lib/theme";

export default function NewChatScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const userName = useAuth((s) => s.session?.userName ?? "");
  const repository = useDefaultRepository();
  const repositories = useRepositories();
  const setRepository = useRepo((s) => s.setRepository);

  const pickRepository = (): void => {
    const options = repositories.data ?? [];
    ActionSheetIOS.showActionSheetWithOptions(
      {
        title: "Repository",
        options: [...options, "No repository", "Cancel"],
        cancelButtonIndex: options.length + 1,
      },
      (index) => {
        if (index < options.length) setRepository(options[index]);
        else if (index === options.length) setRepository(null);
      },
    );
  };
  const invalidateTasks = useInvalidateTasks();
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
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

  const send = async (text: string): Promise<void> => {
    setSending(true);
    setError(null);
    try {
      const task = await createAndRunTask({
        prompt: text,
        repository: repository.data ?? null,
        model,
      });
      invalidateTasks();
      router.replace({
        pathname: "/(drawer)/task/[id]",
        params: { id: task.id },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
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
        {repository.isLoading ? null : (
          <Pressable
            onPress={pickRepository}
            hitSlop={10}
            style={({ pressed }) => pressed && { opacity: 0.5 }}
          >
            <Text style={styles.repo}>
              {repository.data ?? "Choose a repository"}
            </Text>
          </Pressable>
        )}
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </Animated.View>
      <KeyboardStickyView offset={{ closed: 0, opened: insets.bottom }}>
        <View style={[styles.composer, { paddingBottom: insets.bottom + 8 }]}>
          <Composer
            placeholder="Chat with PostHog"
            model={model}
            onModelChange={setModel}
            onSend={send}
            sending={sending}
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
  repo: { fontFamily: fonts.mono, fontSize: 12, color: colors.inkMute },
  error: {
    color: colors.danger,
    fontFamily: fonts.sans,
    fontSize: 13,
    textAlign: "center",
    marginTop: 8,
  },
  composer: { paddingHorizontal: 12 },
});
