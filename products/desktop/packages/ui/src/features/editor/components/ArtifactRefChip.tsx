import { DownloadSimpleIcon } from "@phosphor-icons/react";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useArtifactDownload } from "@posthog/ui/features/sessions/useArtifactDownload";
import { useRunArtifacts } from "@posthog/ui/features/sessions/useRunArtifacts";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
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
    return <ArtifactChipShell label={label} name={displayName} disabled />;
  }
  const artifactId = artifact?.id;
  if (!artifactId) return <>{fallback}</>;

  const name = artifact.name;
  const sizeLabel = formatFileSize(artifact.size);

  return (
    <ArtifactChipShell
      label={label}
      name={name}
      sizeLabel={sizeLabel}
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

/** Presentation only, exported for stories. */
export function ArtifactChipShell({
  label,
  name,
  sizeLabel,
  onOpen,
  onDownload,
  downloading,
  disabled,
}: {
  label: ReactNode;
  name?: string;
  sizeLabel?: string | null;
  onOpen?: () => void;
  onDownload?: () => void;
  downloading?: boolean;
  disabled?: boolean;
}) {
  return (
    // A span, not a button: this renders inside a paragraph, so the two halves
    // have to be siblings rather than a button nested in a button.
    <span className="mx-0.5 inline-flex max-w-full cursor-default items-stretch overflow-hidden rounded-md border border-border bg-muted align-middle text-[0.95em] leading-normal">
      <button
        type="button"
        onClick={onOpen}
        disabled={disabled || !onOpen}
        aria-label={name ? `Open ${name}` : undefined}
        className="flex min-w-0 items-center gap-1 px-1.5 py-0.5 text-left transition-colors enabled:cursor-pointer enabled:hover:bg-gray-3"
      >
        {typeof name === "string" && <FileIcon filename={name} size={12} />}
        <span className="min-w-0 truncate">{label}</span>
        {sizeLabel && (
          <span className="shrink-0 text-muted-foreground">{sizeLabel}</span>
        )}
      </button>
      {onDownload && (
        <Tooltip content={downloading ? "Downloading…" : "Download"}>
          <button
            type="button"
            onClick={onDownload}
            disabled={downloading}
            aria-label={name ? `Download ${name}` : "Download"}
            className="flex shrink-0 items-center self-stretch border-border border-l px-1.5 text-muted-foreground transition-colors enabled:cursor-pointer enabled:hover:bg-gray-3 enabled:hover:text-foreground disabled:opacity-60"
          >
            <DownloadSimpleIcon size={12} />
          </button>
        </Tooltip>
      )}
    </span>
  );
}
