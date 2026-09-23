import { Text } from "@components/text";
import type { VoiceState } from "@posthog/core/voice/schemas";
import { ActivityIndicator, Pressable, View } from "react-native";

export function VoiceControls({
  state,
  onPress,
  disabled = false,
}: {
  state: VoiceState;
  onPress(): void;
  disabled?: boolean;
}): React.JSX.Element {
  const busy = state === "connecting" || state === "closing";
  const label =
    state === "connecting"
      ? "Cancel voice connection"
      : state === "closing"
        ? "Ending voice"
        : state === "connected"
          ? "End voice"
          : "Start voice";
  return (
    <View className="gap-1 px-4 py-2">
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityState={{ disabled: disabled || state === "closing", busy }}
        disabled={disabled || state === "closing"}
        onPress={onPress}
        className="min-h-11 flex-row items-center justify-center gap-2 rounded-lg border border-gray-6 px-3 py-2"
      >
        {busy ? <ActivityIndicator /> : null}
        <Text className="text-gray-12">{label}</Text>
      </Pressable>
      <Text accessibilityLiveRegion="polite" className="text-gray-11 text-xs">
        {disabled
          ? "Finish dictation to start voice."
          : state === "error"
            ? "Voice could not connect. Check microphone access and try again."
            : state === "connected"
              ? "Voice is on. End voice to stop the microphone. Your task will keep running."
              : state === "connecting"
                ? "Connecting to voice..."
                : state === "closing"
                  ? "Microphone is off. Ending the voice session..."
                  : "Audio and recent messages go to OpenAI. Calls end after 5 minutes."}
      </Text>
    </View>
  );
}
