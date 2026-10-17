import { Host, Image as SymbolImage } from "@expo/ui/swift-ui";
import { getReasoningEffortOptions } from "@posthog/shared";
import * as Haptics from "expo-haptics";
import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
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
  FadeIn,
  FadeOut,
  LinearTransition,
  ZoomIn,
  ZoomOut,
} from "react-native-reanimated";
import { Glass } from "@/components/Glass";
import { ArrowUpIcon, StopIcon } from "@/components/Icons";
import { Waveform } from "@/components/Waveform";
import { MAX_PHOTOS, type Photo, pickPhotos } from "@/lib/attachments";
import { sessionIdentity } from "@/lib/auth";
import { beginSend, type Draft, loadDraft, saveDraft } from "@/lib/cache";
import { useComposer } from "@/lib/composer";
import { useDictation } from "@/lib/dictation";
import { shortModelName } from "@/lib/models";
import { colors, fonts, radius } from "@/lib/theme";

function Glyph({
  name,
  size = 17,
  color = colors.ink,
}: {
  name: "plus" | "mic" | "xmark" | "stop.fill";
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
  // Where the unsent text and photos are kept; omit to keep no draft.
  draftKey?: string;
}

const DRAFT_DELAY = 400;

export function Composer({
  placeholder,
  repository,
  onSend,
  onStop,
  busy,
  sending,
  autoFocus,
  draftKey,
}: ComposerProps) {
  const router = useRouter();
  const [initial] = useState(() => (draftKey ? loadDraft(draftKey) : null));
  const [text, setText] = useState(initial?.text ?? "");
  const [photos, setPhotos] = useState<Photo[]>(initial?.photos ?? []);
  const latest = useRef<Draft>({ text, photos });
  const hydratedKey = useRef(draftKey);
  const withSpeech = (base: string, heard: string): string =>
    [base.trim(), heard.trim()].filter(Boolean).join(" ");
  const dictation = useDictation((heard) =>
    setText((current) => withSpeech(current, heard)),
  );
  // Drawer screens stay mounted when another route gets focus, so stop the microphone on blur.
  useFocusEffect(useCallback(() => dictation.cancel, [dictation.cancel]));
  const { model, adapter, reasoning } = useComposer();
  const effort = getReasoningEffortOptions(adapter, model)?.find(
    (option) => option.value === reasoning,
  )?.name;
  const shown = dictation.active
    ? withSpeech(text, dictation.transcript)
    : text;
  const canSend =
    (shown.trim().length > 0 || photos.length > 0) &&
    !sending &&
    !dictation.stopping;

  useEffect(() => {
    latest.current = { text, photos };
  }, [text, photos]);

  // The chat screen stays mounted across chats, so swap drafts with the key.
  useEffect(() => {
    if (draftKey === hydratedKey.current) return;
    hydratedKey.current = draftKey;
    const saved = draftKey ? loadDraft(draftKey) : null;
    setText(saved?.text ?? "");
    setPhotos(saved?.photos ?? []);
  }, [draftKey]);

  useEffect(() => {
    if (!draftKey) return;
    const timer = setTimeout(
      () => saveDraft(draftKey, { text, photos }),
      DRAFT_DELAY,
    );
    return () => clearTimeout(timer);
  }, [draftKey, text, photos]);

  // Leaving inside the debounce window still keeps the draft. A sign-out or
  // project switch remounts the app after the session changed, so skip that.
  useEffect(() => {
    if (!draftKey) return;
    const identity = sessionIdentity();
    return () => {
      if (sessionIdentity() === identity) saveDraft(draftKey, latest.current);
    };
  }, [draftKey]);

  const attach = async (): Promise<void> => {
    try {
      const picked = await pickPhotos(MAX_PHOTOS - photos.length);
      if (picked.length) setPhotos((current) => [...current, ...picked]);
    } catch {
      Alert.alert("Could not open photos", "Check photo access in Settings.");
    }
  };

  const startDictation = (): void => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
    dictation.start();
  };

  const stopDictation = async (): Promise<void> => {
    const heard = await dictation.stop();
    if (heard !== null) setText((current) => withSpeech(current, heard));
  };

  // The input shows the live transcript, so an edit already holds it. Dropping the transcript keeps it from being added twice.
  const editText = (value: string): void => {
    if (dictation.active) dictation.cancel();
    setText(value);
  };

  const submit = async (): Promise<void> => {
    if (dictation.stopping || sending) return;
    const heard = dictation.active ? await dictation.stop() : "";
    // An edit, cancel or blur during the wait ends the send and keeps the draft.
    if (heard === null) return;
    const value = withSpeech(text, heard).trim();
    if ((!value && !photos.length) || sending) return;
    const attached = photos;
    setText("");
    setPhotos([]);
    latest.current = { text: "", photos: [] };
    const settle = draftKey
      ? beginSend(draftKey, { text: value, photos: attached })
      : undefined;
    try {
      await onSend(value, attached);
    } catch {
      settle?.(false);
      if (hydratedKey.current === draftKey) {
        // Keep a draft the person started while the send was in flight.
        setText((current) => (current.trim() ? current : value));
        setPhotos((current) => (current.length ? current : attached));
      }
      return;
    }
    settle?.(true);
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
        value={shown}
        onChangeText={editText}
        placeholder={placeholder}
        placeholderTextColor={colors.inkMute}
        style={styles.input}
        multiline
        autoFocus={autoFocus}
      />
      <View style={styles.row}>
        {dictation.active ? (
          <Pressable
            accessibilityLabel="Cancel dictation"
            onPress={dictation.cancel}
            style={({ pressed }) => [
              styles.circle,
              pressed && { opacity: 0.6 },
            ]}
          >
            <Glyph name="xmark" />
          </Pressable>
        ) : (
          <Pressable
            accessibilityLabel="Add photos"
            onPress={attach}
            disabled={photos.length >= MAX_PHOTOS}
            style={({ pressed }) => [
              styles.circle,
              pressed && { opacity: 0.6 },
            ]}
          >
            <Glyph name="plus" />
          </Pressable>
        )}
        {dictation.active ? (
          <Animated.View entering={FadeIn.duration(200)} style={styles.middle}>
            <Waveform levels={dictation.levels} head={dictation.head} />
          </Animated.View>
        ) : (
          <Animated.View
            entering={FadeIn.duration(200)}
            exiting={FadeOut.duration(120)}
            style={styles.middle}
          >
            <Pressable
              onPress={() => router.push("/config")}
              style={({ pressed }) => [
                styles.pill,
                pressed && { opacity: 0.6 },
              ]}
            >
              <Text style={styles.pillText} numberOfLines={1}>
                {shortModelName(model)}
                {effort ? (
                  <Text style={styles.pillMuted}> {effort}</Text>
                ) : null}
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
          </Animated.View>
        )}
        <Pressable
          accessibilityLabel={dictation.active ? "Stop dictation" : "Dictate"}
          onPress={dictation.active ? stopDictation : startDictation}
          style={({ pressed }) => [styles.circle, pressed && { opacity: 0.6 }]}
        >
          <Glyph
            name={dictation.active ? "stop.fill" : "mic"}
            size={dictation.active ? 14 : 17}
          />
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
  // Holds the pills or the waveform between the left button and the mic.
  middle: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
});
