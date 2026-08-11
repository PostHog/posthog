import type { TaskRunArtifact } from "@posthog/shared";
import {
  CaretDown,
  CaretRight,
  Export,
  File as FileIcon,
  Plus,
} from "phosphor-react-native";
import { useCallback, useState } from "react";
import { ActivityIndicator, Alert, Pressable, Text, View } from "react-native";
import { shareUrl } from "@/lib/shareUrl";
import { useThemeColors } from "@/lib/theme";
import { presignTaskRunArtifact } from "../api";
import { AttachmentSheet } from "../composer/attachments/AttachmentSheet";
import {
  captureFromCamera,
  pickDocument,
  pickPhotoFromLibrary,
} from "../composer/attachments/pickers";
import type { PendingAttachment } from "../composer/attachments/types";
import { useTaskArtifacts } from "../hooks/useTaskArtifacts";
import { useUploadTaskRunArtifact } from "../hooks/useUploadTaskRunArtifact";
import { formatArtifactSize } from "../utils/artifactPreview";
import { artifactTypeLabel } from "../utils/artifactTypes";
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
  const [collapsed, setCollapsed] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const upload = useUploadTaskRunArtifact(taskId, runId);

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
        await shareUrl(url, artifact.name);
      } catch {
        Alert.alert("Couldn't share file", "Please try again.");
      } finally {
        setSharingId(null);
      }
    },
    [taskId, runId],
  );

  const pickAndUpload = useCallback(
    async (pick: () => Promise<PendingAttachment | null>): Promise<void> => {
      const attachment = await pick();
      // Null means the user cancelled or denied permission; the picker has
      // already explained why, so stay quiet.
      if (attachment) upload.mutate(attachment);
    },
    [upload],
  );

  // The section is the only place to add a file, so it stays visible on a
  // terminal run even before anything has been uploaded.
  if (!taskId || !runId || !enabled) return null;

  const files = artifacts ?? [];
  const uploading = upload.isPending;

  return (
    <View className="mx-4 mb-2 rounded-lg border border-gray-5 bg-gray-2 p-3">
      <View className="flex-row items-center justify-between">
        <Pressable
          onPress={() => setCollapsed((value) => !value)}
          hitSlop={6}
          accessibilityRole="button"
          accessibilityLabel={`Files (${files.length})`}
          accessibilityState={{ expanded: !collapsed }}
          className="flex-row items-center gap-1.5 py-1 active:opacity-60"
        >
          {collapsed ? (
            <CaretRight size={14} color={themeColors.gray[12]} />
          ) : (
            <CaretDown size={14} color={themeColors.gray[12]} />
          )}
          <Text className="font-semibold text-[13px] text-gray-12">
            Files ({files.length})
          </Text>
        </Pressable>
        <Pressable
          onPress={() => setPickerOpen(true)}
          hitSlop={8}
          disabled={uploading}
          accessibilityRole="button"
          accessibilityLabel="Add file"
          className="flex-row items-center gap-1 rounded-md bg-gray-3 px-2 py-1 active:opacity-60 disabled:opacity-50"
        >
          <Plus size={12} color={themeColors.gray[12]} weight="bold" />
          <Text className="text-[12px] text-gray-12">Add file</Text>
        </Pressable>
      </View>

      {collapsed ? null : (
        <View className="mt-2 gap-1">
          {files.map((artifact) => {
            const sharingKey = artifact.id ?? artifact.storage_path;
            const size = formatArtifactSize(artifact.size);
            const typeLabel = artifactTypeLabel(artifact.type);
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
                  {typeLabel ? (
                    <Text className="rounded bg-gray-3 px-1.5 py-0.5 text-[10px] text-gray-10 uppercase">
                      {typeLabel}
                    </Text>
                  ) : null}
                  {size ? (
                    <Text className="text-[12px] text-gray-9">{size}</Text>
                  ) : null}
                </Pressable>
                <Pressable
                  hitSlop={8}
                  className="active:opacity-60"
                  disabled={!artifact.storage_path}
                  onPress={() => void shareArtifact(artifact)}
                  accessibilityRole="button"
                  accessibilityLabel={`Share ${artifact.name ?? "artifact"}`}
                >
                  {sharingId === sharingKey ? (
                    <ActivityIndicator
                      size="small"
                      color={themeColors.gray[11]}
                    />
                  ) : (
                    <Export size={16} color={themeColors.gray[11]} />
                  )}
                </Pressable>
              </View>
            );
          })}

          {uploading ? (
            <View className="flex-row items-center gap-3 rounded-md bg-background px-2 py-1.5">
              <ActivityIndicator size="small" color={themeColors.gray[11]} />
              <Text
                className="flex-1 text-[13px] text-gray-11"
                numberOfLines={1}
              >
                Uploading {upload.variables?.fileName ?? "file"}…
              </Text>
            </View>
          ) : null}

          {upload.isError ? (
            <View className="flex-row items-center gap-3 rounded-md bg-background px-2 py-1.5">
              <Text
                className="flex-1 text-[12px] text-status-error"
                numberOfLines={2}
              >
                {upload.error instanceof Error
                  ? upload.error.message
                  : "Upload failed."}
              </Text>
              <Pressable
                hitSlop={8}
                onPress={() => {
                  const failed = upload.variables;
                  if (failed) upload.mutate(failed);
                }}
                accessibilityRole="button"
                accessibilityLabel="Retry upload"
                className="rounded-md bg-gray-3 px-2 py-1 active:opacity-60"
              >
                <Text className="text-[12px] text-gray-12">Retry</Text>
              </Pressable>
            </View>
          ) : null}

          {files.length === 0 && !uploading && !upload.isError ? (
            <Text className="px-2 py-1.5 text-[12px] text-gray-10">
              No files yet. Add one to keep it with this run.
            </Text>
          ) : null}
        </View>
      )}

      <AttachmentSheet
        open={pickerOpen}
        onClose={() => setPickerOpen(false)}
        onPickPhoto={() => void pickAndUpload(pickPhotoFromLibrary)}
        onPickCamera={() => void pickAndUpload(captureFromCamera)}
        onPickDocument={() => void pickAndUpload(pickDocument)}
      />

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
