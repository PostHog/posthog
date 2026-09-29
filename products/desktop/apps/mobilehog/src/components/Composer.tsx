import {
  formatGatewayModelName,
  getReasoningEffortOptions,
} from "@posthog/shared";
import { useRouter } from "expo-router";
import { useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { ArrowUpIcon, MicrophoneIcon, StopIcon } from "@/components/Icons";
import { captureFailure, captureOutcome } from "@/lib/analytics";
import { useComposer } from "@/lib/composer";
import { useDraft } from "@/lib/drafts";
import { useConnectivity } from "@/lib/offline";
import { MAX_PHOTOS, type PendingPhoto, pickPhoto } from "@/lib/photos";
import { useModels } from "@/lib/queries";
import { colors, fonts } from "@/lib/theme";
import { useDictation } from "@/lib/useDictation";

interface ComposerProps {
  placeholder: string;
  draftId: string;
  // Shown as a second pill when provided (null = no repository chosen).
  repository?: string | null;
  disabled?: boolean;
  onSend: (
    text: string,
    photos: PendingPhoto[],
    draft: { taskId?: string; saveTaskId: (id: string) => Promise<void> },
  ) => void | Promise<void>;
  onStop?: () => void;
  busy?: boolean;
  sending?: boolean;
  autoFocus?: boolean;
}

export function Composer({
  placeholder,
  draftId,
  repository,
  disabled,
  onSend,
  onStop,
  busy,
  sending,
  autoFocus,
}: ComposerProps) {
  const router = useRouter();
  const online = useConnectivity((state) => state.online);
  const draft = useDraft(draftId);
  const { text, photos } = draft;
  const setText = (value: string): void => draft.update({ text: value });
  const setPhotos = (
    change: (current: PendingPhoto[]) => PendingPhoto[],
  ): void => draft.update((current) => ({ photos: change(current.photos) }));
  const inputRef = useRef<TextInput>(null);
  const [focused, setFocused] = useState(false);
  const voice = useDictation((value) => {
    draft.update((current) => ({
      text: `${current.text.trimEnd()}${current.text.trim() ? " " : ""}${value}`,
    }));
  });
  const dictating = voice.status !== "idle";
  const [picking, setPicking] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submittingRef = useRef(false);
  const { model, adapter, reasoning } = useComposer();
  const models = useModels();
  const found = models.data?.find((candidate) => candidate.id === model);
  const effort = getReasoningEffortOptions(adapter, model)?.find(
    (option) => option.value === reasoning,
  )?.name;
  const canSend =
    (text.trim().length > 0 || photos.length > 0) &&
    !sending &&
    !submitting &&
    !picking &&
    !disabled &&
    !dictating &&
    draft.ready &&
    online;

  const addPhoto = async (): Promise<void> => {
    if (picking || photos.length >= MAX_PHOTOS) return;
    setPicking(true);
    setError(null);
    try {
      const photo = await pickPhoto();
      if (photo) setPhotos((current) => [...current, photo]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add photo.");
    } finally {
      setPicking(false);
    }
  };

  const submit = async (): Promise<void> => {
    const value = text.trim();
    if (
      !online ||
      !draft.ready ||
      (!value && !photos.length) ||
      picking ||
      dictating ||
      sending ||
      disabled ||
      submittingRef.current
    )
      return;
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      await onSend(value, photos, {
        taskId: draft.taskId,
        saveTaskId: (taskId) => draft.save({ taskId }),
      });
      captureOutcome("send_message", true, { has_images: photos.length > 0 });
      try {
        await draft.clear();
      } catch {
        setError(
          "Message sent, but the saved draft could not be cleared. Check the conversation before sending it again.",
        );
      }
    } catch (cause) {
      captureOutcome("send_message", false, { has_images: photos.length > 0 });
      captureFailure("send_message", cause);
      setError(
        cause instanceof Error ? cause.message : "Could not send message.",
      );
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const expanded = focused || text.length > 0 || photos.length > 0 || dictating;
  const photoButton = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Add photo"
      onPress={() => void addPhoto()}
      disabled={
        picking ||
        submitting ||
        sending ||
        disabled ||
        dictating ||
        !draft.ready ||
        photos.length >= MAX_PHOTOS
      }
      style={styles.iconButton}
    >
      {picking ? (
        <ActivityIndicator size="small" color={colors.ink} />
      ) : (
        <Text style={styles.addText}>+</Text>
      )}
    </Pressable>
  );
  const voiceButton = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={dictating ? "Stop dictation" : "Dictate message"}
      disabled={
        disabled ||
        !draft.ready ||
        submitting ||
        sending ||
        picking ||
        voice.status === "starting" ||
        voice.status === "stopping"
      }
      onPress={() =>
        voice.status === "recording" ? voice.stop() : void voice.start()
      }
      style={styles.iconButton}
    >
      {voice.status === "starting" || voice.status === "stopping" ? (
        <ActivityIndicator size="small" color={colors.accent} />
      ) : dictating ? (
        <StopIcon color={colors.accent} />
      ) : (
        <MicrophoneIcon />
      )}
    </Pressable>
  );
  const sendButton =
    busy && onStop ? (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Stop task"
        onPress={onStop}
        style={styles.send}
      >
        <StopIcon />
      </Pressable>
    ) : (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Send message"
        onPress={() => void submit()}
        disabled={!canSend}
        style={[styles.send, !canSend && styles.sendDisabled]}
      >
        {sending || submitting ? (
          <ActivityIndicator size="small" color={colors.darkText} />
        ) : (
          <ArrowUpIcon />
        )}
      </Pressable>
    );

  return (
    <View style={styles.shell}>
      {draft.error ? (
        <Text accessibilityRole="alert" style={styles.error}>
          {draft.error}
        </Text>
      ) : null}
      {photos.length > 0 ? (
        <View style={styles.photos}>
          {photos.map((photo) => (
            <View key={photo.id} style={styles.photo}>
              <Image source={{ uri: photo.uri }} style={styles.thumbnail} />
              <Pressable
                accessibilityRole="button"
                accessibilityLabel={`Remove ${photo.name}`}
                onPress={() =>
                  setPhotos((current) =>
                    current.filter((item) => item.id !== photo.id),
                  )
                }
                disabled={submitting}
                style={styles.removePhoto}
              >
                <Text style={styles.removeText}>×</Text>
              </Pressable>
            </View>
          ))}
        </View>
      ) : null}
      <View style={styles.inputRow}>
        {!expanded ? photoButton : null}
        <TextInput
          ref={inputRef}
          value={text}
          onChangeText={setText}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={placeholder}
          accessibilityLabel={placeholder}
          placeholderTextColor={colors.inkMute}
          style={styles.input}
          editable={
            draft.ready && !submitting && !sending && !disabled && !dictating
          }
          multiline
          autoFocus={autoFocus}
        />
        {!expanded ? (
          <>
            {voiceButton}
            {sendButton}
          </>
        ) : null}
      </View>
      {dictating ? (
        <View style={styles.dictation}>
          <Text style={styles.dictationText}>
            {voice.preview ||
              (voice.status === "recording"
                ? "Listening"
                : voice.status === "stopping"
                  ? "Finishing dictation"
                  : "Starting microphone")}
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Cancel dictation"
            onPress={voice.cancel}
            style={styles.iconButton}
          >
            <Text style={styles.addText}>×</Text>
          </Pressable>
        </View>
      ) : null}
      {error || voice.error ? (
        <Text style={styles.error}>{error || voice.error}</Text>
      ) : null}
      {expanded ? (
        <View style={styles.row}>
          {photoButton}
          <Pressable
            onPress={() => router.push("/config")}
            accessibilityRole="button"
            accessibilityLabel="Choose model"
            style={({ pressed }) => [
              styles.pill,
              styles.model,
              pressed && { opacity: 0.6 },
            ]}
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
          {voiceButton}
          {sendButton}
        </View>
      ) : null}
      {!expanded && repository !== undefined ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Choose repository"
          onPress={() => router.push("/picker")}
          style={styles.pill}
        >
          <Text style={styles.pillText} numberOfLines={1}>
            {repository ? repository.split("/").pop() : "Choose repository"}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  shell: {
    borderRadius: 28,
    paddingHorizontal: 8,
    paddingVertical: 6,
    backgroundColor: colors.surface,
    borderColor: colors.line,
    borderWidth: StyleSheet.hairlineWidth,
    gap: 4,
    overflow: "hidden",
  },
  inputRow: { flexDirection: "row", alignItems: "center", gap: 2 },
  model: { flexShrink: 1 },
  dictation: { flexDirection: "row", alignItems: "center", paddingLeft: 8 },
  dictationText: {
    flex: 1,
    color: colors.inkSoft,
    fontFamily: fonts.sans,
    fontSize: 15,
  },
  photos: { flexDirection: "row", gap: 10, padding: 8 },
  photo: { width: 56, height: 56 },
  thumbnail: { width: 56, height: 56, borderRadius: 10 },
  removePhoto: {
    position: "absolute",
    top: -6,
    right: -6,
    width: 24,
    height: 24,
    borderRadius: 12,
    backgroundColor: colors.dark,
    alignItems: "center",
    justifyContent: "center",
  },
  removeText: { fontSize: 18, color: colors.darkText, lineHeight: 21 },
  error: { fontFamily: fonts.sans, fontSize: 13, color: colors.danger },
  input: {
    fontFamily: fonts.sans,
    fontSize: 17,
    lineHeight: 22,
    color: colors.ink,
    maxHeight: 140,
    flex: 1,
    minHeight: 40,
    paddingHorizontal: 8,
    paddingVertical: 8,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 2 },
  iconButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  addText: { fontFamily: fonts.sansMedium, fontSize: 26, color: colors.ink },
  pill: { paddingHorizontal: 8, minHeight: 40, justifyContent: "center" },
  pillWide: { maxWidth: 110, flexShrink: 1 },
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
