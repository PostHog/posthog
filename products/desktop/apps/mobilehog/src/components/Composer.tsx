import { Host, Image } from "@expo/ui/swift-ui";
import { getReasoningEffortOptions } from "@posthog/shared";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  type ColorValue,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Glass } from "@/components/Glass";
import { ArrowUpIcon, StopIcon } from "@/components/Icons";
import { useComposer } from "@/lib/composer";
import { colors, fonts, radius } from "@/lib/theme";

const BRANDS = new Set(["claude", "gemini", "anthropic", "openai"]);
const ACRONYMS = new Set(["gpt", "o"]);

// "claude-opus-5-5" reads as "Opus 5.5": no brand, version digits joined.
function shortModelName(id: string): string {
  const parts = (id.split("/").pop() ?? id).split("-");
  // Keep the brand when it is the only name, as in "gemini-3-pro".
  const dropBrand = BRANDS.has(parts[0]) && /^[a-z]/.test(parts[1] ?? "");
  const words = parts
    .slice(dropBrand ? 1 : 0)
    .filter((part) => !/^\d{8}$/.test(part));
  const out: string[] = [];
  for (const word of words) {
    const previous = out[out.length - 1];
    if (/^\d+$/.test(word) && previous && /^\d+(\.\d+)*$/.test(previous)) {
      out[out.length - 1] = `${previous}.${word}`;
    } else if (ACRONYMS.has(word)) {
      out.push(word.toUpperCase());
    } else {
      out.push(word.charAt(0).toUpperCase() + word.slice(1));
    }
  }
  return out.join(" ");
}

function Glyph({
  name,
  color = colors.ink,
}: {
  name: "plus" | "mic";
  color?: ColorValue;
}) {
  return (
    <Host matchContents>
      <Image systemName={name} size={17} color={color} />
    </Host>
  );
}

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
      />
      <View style={styles.row}>
        <Pressable
          accessibilityLabel="Add attachment"
          style={({ pressed }) => [styles.circle, pressed && { opacity: 0.6 }]}
        >
          <Glyph name="plus" />
        </Pressable>
        <Pressable
          onPress={() => router.push("/config")}
          style={({ pressed }) => [styles.pill, pressed && { opacity: 0.6 }]}
        >
          <Text style={styles.pillText} numberOfLines={1}>
            {shortModelName(model)}
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
        <Pressable
          accessibilityLabel="Dictate"
          style={({ pressed }) => [styles.circle, pressed && { opacity: 0.6 }]}
        >
          <Glyph name="mic" />
        </Pressable>
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

const CONTROL = 40;

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
  row: { flexDirection: "row", alignItems: "center", gap: 6 },
  circle: {
    width: CONTROL,
    height: CONTROL,
    borderRadius: CONTROL / 2,
    backgroundColor: colors.fill,
    alignItems: "center",
    justifyContent: "center",
  },
  pill: {
    height: CONTROL,
    justifyContent: "center",
    backgroundColor: colors.fill,
    paddingHorizontal: 12,
    borderRadius: radius.pill,
  },
  // Only the repository gives way when the row runs out of room.
  pillWide: { flexShrink: 1, maxWidth: 130 },
  pillText: { fontFamily: fonts.sansMedium, fontSize: 15, color: colors.ink },
  pillMuted: { color: colors.inkMute },
  send: {
    width: CONTROL,
    height: CONTROL,
    borderRadius: CONTROL / 2,
    backgroundColor: colors.dark,
    alignItems: "center",
    justifyContent: "center",
  },
  sendDisabled: { opacity: 0.3 },
});
