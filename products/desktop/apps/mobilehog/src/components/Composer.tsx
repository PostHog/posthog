import { Host, Image as SymbolImage } from "@expo/ui/swift-ui";
import { getReasoningEffortOptions } from "@posthog/shared";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  type ColorValue,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import Animated, {
  LinearTransition,
  ZoomIn,
  ZoomOut,
} from "react-native-reanimated";
import { Glass } from "@/components/Glass";
import { ArrowUpIcon, StopIcon } from "@/components/Icons";
import { MAX_PHOTOS, type Photo, pickPhotos } from "@/lib/attachments";
import { useComposer } from "@/lib/composer";
import { shortModelName } from "@/lib/models";
import { colors, fonts, radius } from "@/lib/theme";

function Glyph({
  name,
  size = 17,
  color = colors.ink,
}: {
  name: "plus" | "mic" | "xmark";
  size?: number;
  color?: ColorValue;
}) {
  return (
    <Host matchContents>
      <SymbolImage systemName={name} size={size} color={color} />
    </Host>
  );
}

interface ComposerProps {
  placeholder: string;
  // Shown as a second pill when provided (null = no repository chosen).
  repository?: string | null;
  onSend: (text: string, photos: Photo[]) => void | Promise<void>;
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
  const [photos, setPhotos] = useState<Photo[]>([]);
  const { model, adapter, reasoning } = useComposer();
  const effort = getReasoningEffortOptions(adapter, model)?.find(
    (option) => option.value === reasoning,
  )?.name;
  const canSend = (text.trim().length > 0 || photos.length > 0) && !sending;

  const attach = async (): Promise<void> => {
    try {
      const picked = await pickPhotos(MAX_PHOTOS - photos.length);
      if (picked.length) setPhotos((current) => [...current, ...picked]);
    } catch {
      Alert.alert("Could not open photos", "Check photo access in Settings.");
    }
  };

  const submit = async (): Promise<void> => {
    const value = text.trim();
    if ((!value && !photos.length) || sending) return;
    const attached = photos;
    setText("");
    setPhotos([]);
    await onSend(value, attached);
  };

  return (
    <Glass style={styles.shell}>
      {photos.length ? (
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.thumbs}
        >
          {photos.map((photo) => (
            <Animated.View
              key={photo.id}
              entering={ZoomIn.duration(180)}
              exiting={ZoomOut.duration(140)}
              layout={LinearTransition.duration(180)}
            >
              <Image source={{ uri: photo.uri }} style={styles.thumb} />
              <Pressable
                accessibilityLabel="Remove photo"
                hitSlop={8}
                onPress={() =>
                  setPhotos((current) =>
                    current.filter((item) => item.id !== photo.id),
                  )
                }
                style={styles.thumbRemove}
              >
                <Glyph name="xmark" size={10} color={colors.darkText} />
              </Pressable>
            </Animated.View>
          ))}
        </ScrollView>
      ) : null}
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
          accessibilityLabel="Add photos"
          onPress={attach}
          disabled={photos.length >= MAX_PHOTOS}
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

const CONTROL = 36;

const THUMB = 64;

const styles = StyleSheet.create({
  thumbs: { gap: 8, paddingTop: 2, paddingRight: 8 },
  thumb: {
    width: THUMB,
    height: THUMB,
    borderRadius: 14,
    backgroundColor: colors.fill,
  },
  thumbRemove: {
    position: "absolute",
    top: 4,
    right: 4,
    width: 20,
    height: 20,
    borderRadius: 10,
    backgroundColor: "rgba(21, 21, 21, 0.6)",
    alignItems: "center",
    justifyContent: "center",
  },
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
  pillText: { fontFamily: fonts.sansMedium, fontSize: 14, color: colors.ink },
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
