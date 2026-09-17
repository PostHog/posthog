import { useState } from "react";
import {
  ActionSheetIOS,
  ActivityIndicator,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Glass } from "@/components/Glass";
import { ArrowUpIcon, StopIcon } from "@/components/Icons";
import { useModels } from "@/lib/queries";
import { colors, fonts, radius } from "@/lib/theme";

interface ComposerProps {
  placeholder: string;
  model: string;
  onModelChange: (model: string) => void;
  onSend: (text: string) => void | Promise<void>;
  onStop?: () => void;
  busy?: boolean;
  sending?: boolean;
  autoFocus?: boolean;
}

function shortModelName(id: string): string {
  return id.replace(/^claude-/, "").replace(/-/g, " ");
}

export function Composer({
  placeholder,
  model,
  onModelChange,
  onSend,
  onStop,
  busy,
  sending,
  autoFocus,
}: ComposerProps) {
  const [text, setText] = useState("");
  const models = useModels();
  const canSend = text.trim().length > 0 && !sending;

  const pickModel = (): void => {
    const options = models.data ?? [];
    if (options.length === 0) return;
    if (Platform.OS !== "ios") {
      const index = options.findIndex((candidate) => candidate.id === model);
      onModelChange(options[(index + 1) % options.length].id);
      return;
    }
    ActionSheetIOS.showActionSheetWithOptions(
      {
        title: "Model",
        options: [...options.map((candidate) => candidate.id), "Cancel"],
        cancelButtonIndex: options.length,
      },
      (index) => {
        if (index < options.length) onModelChange(options[index].id);
      },
    );
  };

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
          onPress={pickModel}
          style={({ pressed }) => [styles.pill, pressed && { opacity: 0.6 }]}
        >
          <Text style={styles.pillText}>{shortModelName(model)}</Text>
        </Pressable>
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
    backgroundColor: "rgba(28,27,24,0.06)",
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.pill,
  },
  pillText: { fontFamily: fonts.monoMedium, fontSize: 12, color: colors.ink },
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
