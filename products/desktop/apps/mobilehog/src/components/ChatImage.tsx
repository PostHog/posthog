import { extractPromptDisplayContent } from "@posthog/core/sessions/promptContent";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams } from "expo-router";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { getClient } from "@/lib/client";
import { colors, fonts } from "@/lib/theme";

export function ChatImage({
  uri,
  label = "Image",
}: {
  uri: string;
  label?: string;
}) {
  const { id: taskId } = useLocalSearchParams<{ id: string }>();
  const queryClient = useQueryClient();
  const insets = useSafeAreaInsets();
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [ratio, setRatio] = useState(1.5);
  const fileUri = uri.startsWith("/") ? `file://${uri}` : uri;
  const ref = extractPromptDisplayContent([
    { type: "resource_link", uri: fileUri, name: label },
  ]).attachments[0];
  const artifact = ref?.cloudArtifact;
  const preview = useQuery({
    queryKey: ["image-preview", taskId, artifact?.runId, artifact?.artifactId],
    enabled: !!taskId && !!artifact,
    staleTime: 50 * 60_000,
    retry: 1,
    queryFn: async () => {
      if (!artifact) return null;
      const client = getClient();
      const run = await queryClient.fetchQuery({
        queryKey: ["image-artifacts", taskId, artifact.runId],
        queryFn: () => client.getTaskRun(taskId, artifact.runId),
        staleTime: 50 * 60_000,
      });
      const match = run.artifacts?.find(
        (item) => item.id === artifact.artifactId,
      );
      if (!match?.storage_path) throw new Error("Image not found");
      return client.presignTaskRunArtifact(
        taskId,
        artifact.runId,
        match.storage_path,
      );
    },
  });
  // Device file URLs and arbitrary schemes from a message must never be loaded.
  const source = artifact
    ? preview.data
    : /^(https?:\/\/|data:image\/(?:png|jpeg|gif|webp);base64,)/i.test(uri)
      ? uri
      : null;
  useEffect(() => {
    setFailed(false);
    setLoading(!!source);
    setRatio(1.5);
  }, [source]);
  const retry = async () => {
    setFailed(false);
    setLoading(true);
    if (artifact) {
      await queryClient.invalidateQueries({
        queryKey: ["image-artifacts", taskId, artifact.runId],
      });
      await preview.refetch();
    }
  };
  return (
    <View style={styles.root}>
      {!artifact && !source ? (
        <Text style={styles.label}>
          {label} is not available on this device.
        </Text>
      ) : preview.isError || failed ? (
        <Pressable accessibilityRole="button" onPress={retry}>
          <Text style={styles.label}>
            Could not load {label}. Tap to retry.
          </Text>
        </Pressable>
      ) : !source ? (
        <ActivityIndicator color={colors.accent} />
      ) : (
        <>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Expand ${label}`}
            onPress={() => setExpanded(true)}
          >
            <Image
              source={{ uri: source }}
              resizeMode="contain"
              style={{ width: "100%", aspectRatio: ratio, maxHeight: 360 }}
              accessibilityLabel={label}
              onLoad={(event) => {
                const { width, height } = event.nativeEvent.source;
                if (width && height) setRatio(width / height);
                setLoading(false);
              }}
              onError={() => {
                setFailed(true);
                setLoading(false);
              }}
            />
            {loading ? (
              <ActivityIndicator
                style={StyleSheet.absoluteFill}
                color={colors.accent}
              />
            ) : null}
          </Pressable>
          <Modal
            visible={expanded}
            animationType="fade"
            onRequestClose={() => setExpanded(false)}
          >
            <View
              style={[
                styles.fullscreen,
                { paddingTop: insets.top, paddingBottom: insets.bottom },
              ]}
            >
              <Pressable
                accessibilityRole="button"
                onPress={() => setExpanded(false)}
                style={{ padding: 16 }}
              >
                <Text style={styles.label}>Close image</Text>
              </Pressable>
              <Image
                source={{ uri: source }}
                resizeMode="contain"
                style={{ flex: 1, width: "100%" }}
                accessibilityLabel={label}
              />
            </View>
          </Modal>
        </>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    width: "100%",
    minHeight: 60,
    borderRadius: 12,
    overflow: "hidden",
    backgroundColor: colors.code,
  },
  label: {
    fontFamily: fonts.sansMedium,
    fontSize: 14,
    color: colors.accent,
    padding: 8,
  },
  fullscreen: { flex: 1, backgroundColor: colors.bg },
});
