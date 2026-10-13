import { Text } from "@components/text";
import { groupRunArtifactVersions } from "@posthog/core/canvas/runArtifactSchemas";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import { readUploadedArtifactName } from "@posthog/core/sessions/inlineArtifacts";
import type { TaskRunArtifact } from "@posthog/shared";
import { File as FileIcon, GitPullRequest } from "phosphor-react-native";
import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import type { ToolStatus } from "@/features/chat";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";
import { useTaskArtifacts } from "../hooks/useTaskArtifacts";
import { formatArtifactSize } from "../utils/artifactPreview";
import { ArtifactPreview } from "./ArtifactPreview";
import { PrDiffStatsBadge } from "./PrDiffStatsBadge";
import { PrStatusBadge } from "./PrStatusBadge";

function fileKindLabel(name: string): string {
  const extension = name.includes(".") ? name.split(".").pop() : undefined;
  return extension && extension.length <= 4 ? extension.toUpperCase() : "File";
}

function CardRow({
  icon,
  title,
  meta,
  onPress,
  accessibilityLabel,
  trailing,
}: {
  icon: React.ReactNode;
  title: string;
  meta?: string | null;
  onPress?: () => void;
  accessibilityLabel?: string;
  trailing?: React.ReactNode;
}) {
  return (
    <View className="mx-4 my-1 rounded-lg border border-gray-5 bg-gray-2">
      <View className="flex-row items-center gap-2.5 py-2 pr-1.5 pl-2">
        <Pressable
          className="min-w-0 flex-1 flex-row items-center gap-2.5 active:opacity-70"
          disabled={!onPress}
          accessibilityRole="button"
          accessibilityLabel={accessibilityLabel}
          onPress={onPress}
        >
          <View className="h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gray-4">
            {icon}
          </View>
          <View className="min-w-0 flex-1">
            <Text
              className="font-medium text-[13px] text-gray-12"
              numberOfLines={1}
            >
              {title}
            </Text>
            {meta ? (
              <Text className="text-[12px] text-gray-10" numberOfLines={1}>
                {meta}
              </Text>
            ) : null}
          </View>
        </Pressable>
        {trailing ? (
          <View className="shrink-0 flex-row items-center gap-1">
            {trailing}
          </View>
        ) : null}
      </View>
    </View>
  );
}

// The manifest only loads once the run is terminal (`enabled`), so an upload
// mid-run stays in its pending state rather than forcing an eager fetch.
export function InlineUploadedArtifactCard({
  toolData,
  taskId,
  runId,
  enabled,
}: {
  toolData: { status: ToolStatus; args?: Record<string, unknown> };
  taskId?: string;
  runId?: string;
  enabled: boolean;
}) {
  const themeColors = useThemeColors();
  const [preview, setPreview] = useState<TaskRunArtifact | null>(null);
  const name = readUploadedArtifactName(toolData.args) ?? "File";
  const isLoading =
    toolData.status === "pending" || toolData.status === "running";
  const isFailed = toolData.status === "error";

  const { data: artifacts } = useTaskArtifacts(
    taskId,
    runId,
    enabled && !isLoading,
  );
  const resolved = useMemo(() => {
    if (!artifacts) return null;
    return (
      groupRunArtifactVersions(artifacts).find((group) => group.name === name)
        ?.latest ?? null
    );
  }, [artifacts, name]);

  const size = formatArtifactSize(resolved?.size);
  const meta = isLoading
    ? "Uploading…"
    : isFailed
      ? "Upload failed"
      : [fileKindLabel(name), size].filter(Boolean).join(" · ");

  const canOpen = Boolean(resolved?.id && taskId && runId);

  return (
    <>
      <CardRow
        icon={
          isLoading ? (
            <ActivityIndicator size="small" color={themeColors.gray[11]} />
          ) : (
            <FileIcon
              size={16}
              color={isFailed ? themeColors.status.error : themeColors.gray[11]}
            />
          )
        }
        title={name}
        meta={meta}
        accessibilityLabel={`View ${name}`}
        onPress={canOpen ? () => setPreview(resolved) : undefined}
      />
      {preview?.id && taskId && runId ? (
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

/** The pull request a run just opened, drawn in the thread where it happened. */
export function InlineCreatedPrCard({ url }: { url: string }) {
  const themeColors = useThemeColors();
  const parsed = parsePrUrl(url);
  const ref = parsed ? `${parsed.repoSlug}#${parsed.number}` : "Pull request";

  return (
    <CardRow
      icon={
        <GitPullRequest
          size={16}
          weight="bold"
          color={themeColors.status.success}
        />
      }
      title="Pull request"
      meta={ref}
      accessibilityLabel={`Open ${ref} on GitHub`}
      onPress={() => openExternalUrl(url)}
      trailing={
        <>
          <PrDiffStatsBadge prUrl={url} />
          <PrStatusBadge prUrl={url} size="sm" hideWhenUnresolved />
        </>
      }
    />
  );
}
