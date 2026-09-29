import {
  formatGatewayModelName,
  getReasoningEffortOptions,
} from "@posthog/shared";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Glass } from "@/components/Glass";
import { ArrowUpIcon, StopIcon } from "@/components/Icons";
import { useComposer } from "@/lib/composer";
import { useModels } from "@/lib/queries";
import { colors, fonts, radius } from "@/lib/theme";

interface ComposerProps {
  placeholder: string;
  // Shown as a second pill when provided (null = no repository chosen).
  repository?: string | null;
  onSend: (text: string) => void | Promise<void>;
  onStop?: () => void;
  busy?: boolean;
  sending?: boolean;
  autoFocus?: boolean;
}

export function Composer({
  placeholder,
  repository,
  onSend,
  onStop,
  busy,
  sending,
  autoFocus,
}: ComposerProps) {
  const router = useRouter();
  const [text, setText] = useState("");
  const { model, adapter, reasoning } = useComposer();
  const models = useModels();
  const found = models.data?.find((candidate) => candidate.id === model);
  const effort = getReasoningEffortOptions(adapter, model)?.find(
    (option) => option.value === reasoning,
  )?.name;
  const canSend = text.trim().length > 0 && !sending;

  const submit = async (): Promise<void> => {
    const value = text.trim();
    if (!value || sending) return;
    setText("");
    await onSend(value);
  };

  return (
    <Glass style={styles.shell}>
      <TextInput
        value={text}
        onChangeText={setText}
        placeholder={placeholder}
        placeholderTextColor={colors.inkMute}
        style={styles.input}
        multiline
        autoFocus={autoFocus}
        keyboardAppearance="light"
      />
      <View style={styles.row}>
        <Pressable
          onPress={() => router.push("/config")}
          style={({ pressed }) => [styles.pill, pressed && { opacity: 0.6 }]}
        >
          <Text style={styles.pillText} numberOfLines={1}>
            {found ? formatGatewayModelName(found) : model}
            {effort ? <Text style={styles.pillMuted}> {effort}</Text> : null}
          </Text>
        </Pressable>
        {repository !== undefined ? (
          <Pressable
            onPress={() => router.push("/picker")}
            style={({ pressed }) => [
              styles.pill,
              styles.pillWide,
              pressed && { opacity: 0.6 },
            ]}
          >
            <Text style={styles.pillText} numberOfLines={1}>
              {repository
                ? (repository.split("/")[1] ?? repository)
                : "No repo"}
            </Text>
          </Pressable>
        ) : null}
        <View style={{ flex: 1 }} />
        {busy && onStop ? (
          <Pressable
            onPress={onStop}
            style={({ pressed }) => [styles.send, pressed && { opacity: 0.7 }]}
          >
            <StopIcon />
          </Pressable>
        ) : (
          <Pressable
            onPress={submit}
            disabled={!canSend}
            style={({ pressed }) => [
              styles.send,
              !canSend && styles.sendDisabled,
              pressed && { opacity: 0.7 },
            ]}
          >
            {sending ? (
              <ActivityIndicator size="small" color={colors.darkText} />
            ) : (
              <ArrowUpIcon />
            )}
          </Pressable>
        )}
      </View>
    </Glass>
  );
}

const styles = StyleSheet.create({
  shell: {
    borderRadius: 28,
    paddingHorizontal: 16,
    paddingTop: 14,
    paddingBottom: 10,
    gap: 10,
    overflow: "hidden",
  },
  input: {
    fontFamily: fonts.sans,
    fontSize: 17,
    lineHeight: 22,
    color: colors.ink,
    maxHeight: 140,
    paddingTop: 0,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  pill: {
    backgroundColor: "rgba(21,21,21,0.06)",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.pill,
  },
  pillWide: { maxWidth: 150 },
  pillText: { fontFamily: fonts.sansMedium, fontSize: 13, color: colors.ink },
  pillMuted: { color: colors.inkMute },
  send: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.dark,
    alignItems: "center",
    justifyContent: "center",
  },
  sendDisabled: { opacity: 0.3 },
});
