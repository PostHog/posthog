import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { groupRunArtifactVersions } from "@posthog/core/canvas/runArtifactSchemas";
import { Button, Spinner } from "@posthog/quill";
import { openPrInReview } from "@posthog/ui/features/code-review/openPrInReview";
import { usePrArtifact } from "@posthog/ui/features/git-interaction/usePrArtifact";
import { openRightPanelSide } from "@posthog/ui/features/navigation/rightPanelSide";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { readUploadedArtifactName } from "@posthog/ui/features/sessions/components/session-update/inlineArtifacts";
import {
  type ToolViewProps,
  useToolCallStatus,
} from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { useSessionSelector } from "@posthog/ui/features/sessions/sessionStore";
import { useRunArtifacts } from "@posthog/ui/features/sessions/useRunArtifacts";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import {
  ArtifactCard,
  stopCardOpen,
} from "@posthog/ui/primitives/ArtifactCard";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { formatFileSize } from "@posthog/ui/utils/formatFileSize";
import { useMemo } from "react";

/** Opens the session's artifacts panel, where the run's other deliverables are. */
function SeeAllArtifactsButton({ taskId }: { taskId: string }) {
  return (
    <Button
      variant="default"
      size="sm"
      onClick={(event) => {
        stopCardOpen(event);
        openRightPanelSide("artifacts", taskId);
      }}
    >
      See all
    </Button>
  );
}

/** What kind of file this is, in the terms its name already gives: "CSV", "PDF". */
function fileKindLabel(name: string): string {
  const extension = name.includes(".") ? name.split(".").pop() : undefined;
  return extension && extension.length <= 4 ? extension.toUpperCase() : "File";
}

/** The uploaded file's id, once the run's manifest carries the name the tool sent. */
function useUploadedArtifact(
  taskId: string | null,
  name: string | null,
): { runId: string; artifactId: string; size: number | undefined } | null {
  const runId = useSessionSelector(taskId ?? undefined, (s) => s?.taskRunId);
  const { data: artifacts } = useRunArtifacts(taskId ?? undefined, runId, {
    staleTime: 15_000,
  });

  return useMemo(() => {
    if (!runId || !name || !artifacts) return null;
    const group = groupRunArtifactVersions(
      artifacts.filter((artifact) => artifact.type === "output"),
    ).find((candidate) => candidate.name === name);
    const id = group?.latest.id;
    return id ? { runId, artifactId: id, size: group?.latest.size } : null;
  }, [artifacts, name, runId]);
}

/**
 * The file an `upload_artifact` call delivers, drawn where the agent produced it
 * rather than only in the panel it lands in. It stands in for the file while the
 * upload runs, then opens it once the run's manifest carries it.
 */
export function UploadedArtifactCard({
  toolCall,
  turnCancelled,
  turnComplete,
}: ToolViewProps) {
  const taskId = useSessionTaskId();
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const name = readUploadedArtifactName(toolCall.rawInput);
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    toolCall.status,
    turnCancelled,
    turnComplete,
  );
  // A file is matched by name, so a re-upload under an existing name would
  // match the version it is about to replace. Resolving by the id the upload
  // returns is the real fix, and waits on that id reaching the tool result.
  const uploaded = useUploadedArtifact(taskId, isLoading ? null : name);
  const title = name ?? "File";

  const delivered = [
    fileKindLabel(title),
    uploaded?.size === undefined ? null : formatFileSize(uploaded.size),
  ]
    .filter(Boolean)
    .join(" · ");
  const meta = isLoading ? (
    <span className="shimmer">Uploading…</span>
  ) : isFailed ? (
    "Upload failed"
  ) : wasCancelled ? (
    "Canceled"
  ) : (
    delivered
  );

  // Until the manifest carries the file there is nothing to preview, so the
  // card falls back to the panel, which lists it as soon as it lands.
  const onOpen = !taskId
    ? undefined
    : uploaded
      ? () =>
          openArtifactTab(taskId, {
            runId: uploaded.runId,
            artifactId: uploaded.artifactId,
            name: title,
          })
      : isLoading || isFailed || wasCancelled
        ? undefined
        : () => openRightPanelSide("artifacts", taskId);

  return (
    <ArtifactCard
      icon={isLoading ? <Spinner /> : <FileIcon filename={title} size={18} />}
      title={title}
      meta={meta}
      onOpen={onOpen}
      actions={taskId ? <SeeAllArtifactsButton taskId={taskId} /> : undefined}
    />
  );
}

/**
 * The pull request a run just opened, drawn in the thread where it happened.
 * Opening it puts the review in the session's own panel, the way every other
 * PR link in the app does.
 */
export function CreatedPrCard({ url }: { url: string }) {
  const taskId = useSessionTaskId();
  const { safeUrl, title, stateLabel, Icon, iconColor } = usePrArtifact(url);

  return (
    <ArtifactCard
      icon={<Icon size={16} weight="bold" style={{ color: iconColor }} />}
      title={title}
      meta={stateLabel ?? undefined}
      onOpen={
        safeUrl
          ? () =>
              taskId
                ? openPrInReview(taskId, safeUrl)
                : openExternalUrl(safeUrl)
          : undefined
      }
      actions={
        <>
          {safeUrl && (
            <Button
              variant="default"
              size="icon-sm"
              aria-label={`Open ${title} on GitHub`}
              onClick={(event) => {
                stopCardOpen(event);
                openExternalUrl(safeUrl);
              }}
            >
              <ArrowSquareOutIcon size={14} />
            </Button>
          )}
          {taskId && <SeeAllArtifactsButton taskId={taskId} />}
        </>
      }
    />
  );
}
