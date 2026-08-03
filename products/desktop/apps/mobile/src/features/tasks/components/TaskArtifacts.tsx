import type { TaskRunArtifact } from "@posthog/shared";
import { ArrowSquareOut, File as FileIcon } from "phosphor-react-native";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, Text, View } from "react-native";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";
import { presignTaskRunArtifact } from "../api";
import { useTaskArtifacts } from "../hooks/useTaskArtifacts";
import { formatArtifactSize } from "../utils/artifactPreview";
import { ArtifactPreview } from "./ArtifactPreview";

interface TaskArtifactsProps {
  taskId: string | undefined;
  runId: string | undefined;
  // Gate the manifest fetch on a terminal run, mirroring desktop.
  enabled: boolean;
}

export function TaskArtifacts({ taskId, runId, enabled }: TaskArtifactsProps) {
  const themeColors = useThemeColors();
  const { data: artifacts } = useTaskArtifacts(taskId, runId, enabled);
  const [preview, setPreview] = useState<TaskRunArtifact | null>(null);
  const [sharingId, setSharingId] = useState<string | null>(null);

  const shareArtifact = useCallback(
    async (artifact: TaskRunArtifact): Promise<void> => {
      if (!taskId || !runId || !artifact.storage_path) return;
      setSharingId(artifact.id ?? artifact.storage_path);
      try {
        const url = await presignTaskRunArtifact(
          taskId,
          runId,
          artifact.storage_path,
        );
        openExternalUrl(url);
      } catch {
        Alert.alert("Couldn't open file", "Please try again.");
      } finally {
        setSharingId(null);
      }
    },
    [taskId, runId],
  );

  if (!taskId || !runId || !artifacts || artifacts.length === 0) return null;

  return (
    <View className="mx-4 mb-2 rounded-lg border border-gray-5 bg-gray-2 p-3">
      <Text className="mb-2 font-semibold text-[13px] text-gray-12">Files</Text>
      <View className="gap-1">
        {artifacts.map((artifact) => {
          const sharingKey = artifact.id ?? artifact.storage_path;
          const size = formatArtifactSize(artifact.size);
          const canPreview = Boolean(artifact.id);
          return (
            <View
              key={sharingKey ?? artifact.name}
              className="flex-row items-center gap-3 rounded-md bg-background px-2 py-1.5"
            >
              <Pressable
                className="min-w-0 flex-1 flex-row items-center gap-2 active:opacity-70"
                disabled={!canPreview}
                onPress={() => setPreview(artifact)}
              >
                <FileIcon size={16} color={themeColors.gray[11]} />
                <Text
                  className="flex-shrink text-[13px] text-gray-12"
                  numberOfLines={1}
                >
                  {artifact.name ?? "artifact"}
                </Text>
                {size ? (
                  <Text className="text-[12px] text-gray-9">{size}</Text>
                ) : null}
              </Pressable>
              <Pressable
                hitSlop={8}
                className="active:opacity-60"
                disabled={!artifact.storage_path}
                onPress={() => void shareArtifact(artifact)}
                accessibilityLabel="Open externally"
              >
                {sharingId === sharingKey ? (
                  <ActivityIndicator
                    size="small"
                    color={themeColors.gray[11]}
                  />
                ) : (
                  <ArrowSquareOut size={16} color={themeColors.gray[11]} />
                )}
              </Pressable>
            </View>
          );
        })}
      </View>

      {preview?.id ? (
        <ArtifactPreview
          taskId={taskId}
          runId={runId}
          artifact={preview}
          onClose={() => setPreview(null)}
        />
      ) : null}
    </View>
  );
}
