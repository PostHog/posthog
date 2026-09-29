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
import { Glass } from "@/components/Glass";
import { ArrowUpIcon, StopIcon } from "@/components/Icons";
import { useComposer } from "@/lib/composer";
import { MAX_PHOTOS, type PendingPhoto, pickPhoto } from "@/lib/photos";
import { useModels } from "@/lib/queries";
import { colors, fonts, radius } from "@/lib/theme";

interface ComposerProps {
  placeholder: string;
  // Shown as a second pill when provided (null = no repository chosen).
  repository?: string | null;
  disabled?: boolean;
  onSend: (text: string, photos: PendingPhoto[]) => void | Promise<void>;
  onStop?: () => void;
  busy?: boolean;
  sending?: boolean;
  autoFocus?: boolean;
}

export function Composer({
  placeholder,
  repository,
  disabled,
  onSend,
  onStop,
  busy,
  sending,
  autoFocus,
}: ComposerProps) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [photos, setPhotos] = useState<PendingPhoto[]>([]);
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
    !disabled;

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
      (!value && !photos.length) ||
      picking ||
      sending ||
      disabled ||
      submittingRef.current
    )
      return;
    submittingRef.current = true;
    setSubmitting(true);
    setError(null);
    try {
      await onSend(value, photos);
      setText("");
      setPhotos([]);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not send message.",
      );
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <Glass style={styles.shell}>
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
      <TextInput
        value={text}
        onChangeText={setText}
        placeholder={placeholder}
        placeholderTextColor={colors.inkMute}
        style={styles.input}
        multiline
        autoFocus={autoFocus}
      />
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <View style={styles.row}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Add photo"
          onPress={() => void addPhoto()}
          disabled={
            picking || submitting || sending || photos.length >= MAX_PHOTOS
          }
          style={[
            styles.addPhoto,
            photos.length >= MAX_PHOTOS && styles.sendDisabled,
          ]}
        >
          {picking ? (
            <ActivityIndicator size="small" color={colors.ink} />
          ) : (
            <Text style={styles.addText}>+</Text>
          )}
        </Pressable>
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
            {sending || submitting ? (
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
  photos: { flexDirection: "row", gap: 10 },
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
    paddingTop: 0,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  addPhoto: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.fill,
    alignItems: "center",
    justifyContent: "center",
  },
  addText: { fontFamily: fonts.sansMedium, fontSize: 26, color: colors.ink },
  pill: {
    backgroundColor: colors.fill,
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
