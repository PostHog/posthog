import { Text } from "@components/text";
import {
  groupRunArtifactVersions,
  type RunArtifactVersions,
  runArtifactUploaderLabel,
  runArtifactVersionKey,
  runArtifactVersionMetaLabel,
  runArtifactVersionShortLabel,
} from "@posthog/core/canvas/runArtifactSchemas";
import { formatRelativeTimeLong, type TaskRunArtifact } from "@posthog/shared";
import { useMutation } from "@tanstack/react-query";
import {
  CaretDown,
  Check,
  DownloadSimple,
  File as FileIcon,
  Package,
  X,
} from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import { useUserQuery } from "@/features/auth";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";
import { dismissTaskRunArtifacts, presignTaskRunArtifact } from "../api";
import { useTaskArtifacts } from "../hooks/useTaskArtifacts";
import { formatArtifactSize } from "../utils/artifactPreview";
import { ArtifactPreview } from "./ArtifactPreview";

type ArtifactGroup = RunArtifactVersions<TaskRunArtifact>;

interface TaskArtifactsProps {
  taskId: string | undefined;
  runId: string | undefined;
  // Gate the manifest fetch on a terminal run, mirroring desktop.
  enabled: boolean;
}

export function TaskArtifacts({ taskId, runId, enabled }: TaskArtifactsProps) {
  const themeColors = useThemeColors();
  const { data: artifacts, refetch } = useTaskArtifacts(taskId, runId, enabled);
  const { data: currentUser } = useUserQuery();
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState<TaskRunArtifact | null>(null);
  const [sharingId, setSharingId] = useState<string | null>(null);
  const [showDismissed, setShowDismissed] = useState(false);
  const [versionPickerFor, setVersionPickerFor] = useState<string | null>(null);
  const [selectedVersionByName, setSelectedVersionByName] = useState<
    Record<string, string>
  >({});
  const [dismissalOverrides, setDismissalOverrides] = useState<
    Record<string, string | null>
  >({});

  const groups = useMemo(
    () =>
      groupRunArtifactVersions(
        (artifacts ?? []).map((artifact) =>
          artifact.id && artifact.id in dismissalOverrides
            ? { ...artifact, dismissed_at: dismissalOverrides[artifact.id] }
            : artifact,
        ),
      ),
    [artifacts, dismissalOverrides],
  );
  const visibleGroups = groups.filter((group) => !group.dismissed);
  const dismissedGroups = groups.filter((group) => group.dismissed);

  const dismissal = useMutation({
    mutationFn: ({
      group,
      dismissed,
    }: {
      group: ArtifactGroup;
      dismissed: boolean;
    }) => {
      const ids = group.versions.flatMap((v) => (v.id ? [v.id] : []));
      if (ids.length !== group.versions.length) {
        throw new Error("Artifact versions are still uploading");
      }
      return dismissTaskRunArtifacts(taskId ?? "", runId ?? "", ids, dismissed);
    },
    // Overlay just the dismissal stamps from the response, then refetch and drop
    // the overlay so the manifest stays the source of truth.
    onSuccess: async (manifest) => {
      setDismissalOverrides((current) => ({
        ...current,
        ...Object.fromEntries(
          manifest.flatMap((entry) =>
            entry.id ? [[entry.id, entry.dismissed_at ?? null]] : [],
          ),
        ),
      }));
      const refreshed = await refetch();
      if (refreshed?.data) setDismissalOverrides({});
    },
    onError: () =>
      Alert.alert("Couldn't update this file", "Please try again."),
  });

  const shareArtifact = async (artifact: TaskRunArtifact): Promise<void> => {
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
  };

  if (!taskId || !runId || groups.length === 0) return null;

  const renderRow = (group: ArtifactGroup) => {
    const pickedIndex = group.versions.findIndex(
      (version) =>
        runArtifactVersionKey(version) === selectedVersionByName[group.name],
    );
    const newestVisibleIndex = group.versions.findIndex(
      (version) => !version.dismissed_at,
    );
    const selectedIndex =
      pickedIndex >= 0 ? pickedIndex : Math.max(newestVisibleIndex, 0);
    const selected = group.versions[selectedIndex];
    const size = formatArtifactSize(selected.size);
    const canPreview = Boolean(selected.id);
    const canChangeDismissal = group.versions.every((version) => version.id);
    const hasVersions = group.versions.length > 1;
    const pickerOpen = versionPickerFor === group.name;

    const meta = [
      runArtifactUploaderLabel(selected, currentUser),
      selected.uploaded_at
        ? formatRelativeTimeLong(selected.uploaded_at)
        : null,
      size,
    ]
      .filter(Boolean)
      .join(" · ");

    return (
      <View
        key={group.name}
        className="rounded-lg border border-gray-5 bg-gray-2"
      >
        <View className="flex-row items-center gap-2.5 py-2 pr-1.5 pl-2">
          <Pressable
            className="min-w-0 flex-1 flex-row items-center gap-2.5 active:opacity-70"
            disabled={!canPreview}
            accessibilityRole="button"
            accessibilityLabel={`View ${group.name}`}
            onPress={() => {
              setOpen(false);
              setPreview(selected);
            }}
          >
            <View className="h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gray-4">
              <FileIcon size={16} color={themeColors.gray[11]} />
            </View>
            <View className="min-w-0 flex-1">
              <Text
                className="font-medium text-[13px] text-gray-12"
                numberOfLines={1}
              >
                {group.name}
              </Text>
              <View className="flex-row items-center gap-1">
                {meta ? (
                  <Text className="text-[12px] text-gray-10" numberOfLines={1}>
                    {meta}
                  </Text>
                ) : null}
                {hasVersions ? (
                  <>
                    {meta ? (
                      <Text className="text-[12px] text-gray-10">·</Text>
                    ) : null}
                    <Pressable
                      hitSlop={6}
                      accessibilityRole="button"
                      accessibilityLabel={`Choose a version of ${group.name}`}
                      onPress={() =>
                        setVersionPickerFor(pickerOpen ? null : group.name)
                      }
                      className="flex-row items-center gap-0.5 active:opacity-60"
                    >
                      <Text className="text-[12px] text-gray-12">
                        {runArtifactVersionShortLabel(
                          selectedIndex,
                          group.versions.length,
                        )}
                      </Text>
                      <CaretDown size={10} color={themeColors.gray[11]} />
                    </Pressable>
                  </>
                ) : null}
              </View>
            </View>
          </Pressable>

          <View className="shrink-0 flex-row items-center gap-1">
            {group.dismissed ? (
              <Pressable
                hitSlop={6}
                disabled={dismissal.isPending || !canChangeDismissal}
                onPress={() => dismissal.mutate({ group, dismissed: false })}
                accessibilityRole="button"
                accessibilityLabel={`Restore ${group.name}`}
                className="rounded-md px-2 py-1.5 active:opacity-60"
              >
                <Text className="font-medium text-[13px] text-gray-12">
                  Restore
                </Text>
              </Pressable>
            ) : (
              <>
                <Pressable
                  hitSlop={6}
                  disabled={!canPreview || sharingId !== null}
                  onPress={() => void shareArtifact(selected)}
                  accessibilityRole="button"
                  accessibilityLabel={`Download ${group.name}`}
                  className="h-8 w-8 items-center justify-center active:opacity-60"
                >
                  {sharingId === (selected.id ?? selected.storage_path) ? (
                    <ActivityIndicator
                      size="small"
                      color={themeColors.gray[11]}
                    />
                  ) : (
                    <DownloadSimple size={16} color={themeColors.gray[11]} />
                  )}
                </Pressable>
                <Pressable
                  hitSlop={6}
                  disabled={dismissal.isPending || !canChangeDismissal}
                  onPress={() => dismissal.mutate({ group, dismissed: true })}
                  accessibilityRole="button"
                  accessibilityLabel={`Dismiss ${group.name}`}
                  className="h-8 w-8 items-center justify-center active:opacity-60"
                >
                  <X size={16} color={themeColors.gray[11]} />
                </Pressable>
              </>
            )}
          </View>
        </View>

        {pickerOpen && hasVersions ? (
          <View className="border-gray-5 border-t px-2 py-1">
            {group.versions.map((version, index) => {
              const key = runArtifactVersionKey(version);
              return (
                <Pressable
                  key={key}
                  onPress={() => {
                    setSelectedVersionByName((current) => ({
                      ...current,
                      [group.name]: key,
                    }));
                    setVersionPickerFor(null);
                  }}
                  className="flex-row items-center gap-2 rounded-md px-2 py-2 active:bg-gray-3"
                >
                  <Text
                    className="min-w-0 flex-1 text-[13px] text-gray-12"
                    numberOfLines={1}
                  >
                    {runArtifactVersionMetaLabel(
                      version,
                      index,
                      group.versions.length,
                      currentUser,
                    )}
                  </Text>
                  {index === selectedIndex ? (
                    <Check size={14} color={themeColors.accent[9]} />
                  ) : null}
                </Pressable>
              );
            })}
          </View>
        ) : null}
      </View>
    );
  };

  const dismissedToggleLabel = showDismissed
    ? "Hide dismissed"
    : `Show ${dismissedGroups.length} dismissed`;

  return (
    <>
      <Pressable
        onPress={() => setOpen(true)}
        hitSlop={8}
        accessibilityRole="button"
        accessibilityLabel={`Files (${visibleGroups.length})`}
        className="h-9 w-9 items-center justify-center active:opacity-60"
      >
        <Package
          size={18}
          color={
            visibleGroups.length > 0
              ? themeColors.accent[11]
              : themeColors.gray[10]
          }
          weight={visibleGroups.length > 0 ? "fill" : "regular"}
        />
        {visibleGroups.length > 0 ? (
          <View className="absolute top-1 right-1 h-4 min-w-4 items-center justify-center rounded-full bg-accent-9 px-0.5">
            <Text className="font-semibold text-[9px] text-accent-contrast">
              {visibleGroups.length}
            </Text>
          </View>
        ) : null}
      </Pressable>

      <SheetContainer open={open} onClose={() => setOpen(false)}>
        {open ? (
          <>
            <View className="flex-row items-center justify-between px-4 pt-2 pb-2">
              <Text className="font-semibold text-[16px] text-gray-12">
                Files
              </Text>
              <Text className="text-[12px] text-gray-10">
                {visibleGroups.length === 1
                  ? "1 file"
                  : `${visibleGroups.length} files`}
              </Text>
            </View>

            <ScrollView
              className="max-h-96 px-4"
              contentContainerStyle={{ paddingBottom: 8, gap: 6 }}
            >
              {visibleGroups.map(renderRow)}
              {showDismissed ? dismissedGroups.map(renderRow) : null}
              {dismissedGroups.length > 0 ? (
                <Pressable
                  onPress={() => setShowDismissed((current) => !current)}
                  accessibilityRole="button"
                  accessibilityLabel={dismissedToggleLabel}
                  className="self-start py-1 active:opacity-60"
                >
                  <Text className="font-medium text-[13px] text-accent-11">
                    {dismissedToggleLabel}
                  </Text>
                </Pressable>
              ) : null}
            </ScrollView>
          </>
        ) : null}
      </SheetContainer>

      {preview?.id ? (
        <ArtifactPreview
          taskId={taskId}
          runId={runId}
          artifact={preview}
          onClose={() => setPreview(null)}
        />
      ) : null}
    </>
  );
}
