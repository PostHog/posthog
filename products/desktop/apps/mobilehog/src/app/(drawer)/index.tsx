import { useRouter } from "expo-router";
import { useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import { KeyboardStickyView } from "react-native-keyboard-controller";
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
} from "@/lib/queries";
import { colors, fonts } from "@/lib/theme";

export default function NewChatScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const userName = useAuth((s) => s.session?.userName ?? "");
  const repository = useDefaultRepository();
  const invalidateTasks = useInvalidateTasks();
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
      <View style={styles.center}>
        <Logomark />
        <Text style={styles.greeting}>
          {userName ? `${userName} returns!` : "G'day"}
        </Text>
        {repository.data ? (
          <Text style={styles.repo}>{repository.data}</Text>
        ) : repository.isLoading ? null : (
          <Text style={styles.repo}>No GitHub repo connected</Text>
        )}
        {error ? <Text style={styles.error}>{error}</Text> : null}
      </View>
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
    fontSize: 13,
    textAlign: "center",
    marginTop: 8,
  },
  composer: { paddingHorizontal: 12 },
});
