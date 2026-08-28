import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useArtifactDownload } from "@posthog/ui/features/sessions/useArtifactDownload";
import { useRunArtifacts } from "@posthog/ui/features/sessions/useRunArtifacts";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import { ArtifactChip } from "@posthog/ui/primitives/ArtifactChip";
import type { ArtifactLinkTarget } from "@posthog/ui/utils/artifactLinks";
import { findArtifactForLink } from "@posthog/ui/utils/artifactLinks";
import { formatFileSize } from "@posthog/ui/utils/formatFileSize";
import type { ReactNode } from "react";

/**
 * An artifact reference inside a message: a chip that opens the file in an
 * artifact tab, with a divided download half for saving it to disk. Supports
 * stable API links and storage URLs from older messages.
 *
 * Renders `fallback` whenever it cannot prove which artifact the link means:
 * another task, a dismissed artifact, or an ambiguous legacy id prefix.
 */
export function ArtifactRefChip({
  target,
  href,
  children,
  fallback,
}: {
  target: ArtifactLinkTarget;
  href: string;
  children: ReactNode;
  fallback: ReactNode;
}) {
  const sessionTaskId = useSessionTaskId();
  // The link carries its own task id, but a message can quote a link from
  // anywhere. Only a link belonging to the task being viewed is opened in
  // place — the artifact tab is scoped to this task, and its API calls are
  // authorized against it.
  const belongsToSession = sessionTaskId === target.taskId;

  // isLoading rather than isPending: a query that is disabled (signed out) is
  // pending forever, and a chip that never resolves is worse than a link.
  const {
    data: artifacts,
    isFetching,
    isLoading,
  } = useRunArtifacts(target.taskId, target.runId, {
    enabled: belongsToSession,
    staleTime: 0,
  });
  const artifact = artifacts ? findArtifactForLink(artifacts, target) : null;

  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const markdownLabel =
    typeof children === "string" && children !== href ? children : undefined;
  const fallbackName =
    target.kind === "legacy-storage" ? target.fileName : markdownLabel;
  const displayName = artifact?.name ?? fallbackName;
  // A bare legacy URL includes the filename, while a stable URL gets its name
  // from the manifest after the refresh completes.
  const label =
    typeof children === "string" && children === href
      ? (displayName ?? children)
      : children;
  const { download, downloadingId } = useArtifactDownload();

  if (!belongsToSession) return <>{fallback}</>;
  // Resolving: hold the chip's shape so the line doesn't reflow once the
  // manifest lands, but keep it inert until there is something to open.
  if (isLoading || (isFetching && !artifact)) {
    return <ArtifactChip label={label} name={displayName} disabled />;
  }
  const artifactId = artifact?.id;
  if (!artifactId) return <>{fallback}</>;

  const name = artifact.name;
  const sizeLabel = formatFileSize(artifact.size);

  return (
    <ArtifactChip
      label={label}
      name={name}
      meta={sizeLabel}
      onOpen={() =>
        openArtifactTab(target.taskId, {
          runId: target.runId,
          artifactId,
          name,
        })
      }
      onDownload={() => {
        void download({
          taskId: target.taskId,
          runId: target.runId,
          artifactId,
          name,
        });
      }}
      downloading={downloadingId === artifactId}
    />
  );
}
