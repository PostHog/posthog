import {
  getPostHogObjectArtifactMetadata,
  groupRunArtifactVersions,
  type PostHogObjectArtifactMetadata,
} from "@posthog/core/canvas/runArtifactSchemas";
import type { SessionService } from "@posthog/core/sessions/sessionService";
import type { TaskRunArtifact } from "@posthog/shared";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { artifactPreviewBlob } from "./artifactPreviewDocument";

const MARKDOWN_EXTENSIONS = new Set(["md", "mdx", "markdown"]);
const HTML_EXTENSIONS = new Set(["html", "htm"]);

export type HtmlPreview = { kind: "html"; html: string };
export type PostHogObjectPreview = {
  kind: "posthog-object";
  metadata: PostHogObjectArtifactMetadata;
};
export type PreviewData = string | Blob | HtmlPreview | PostHogObjectPreview;
export type EditableArtifactKind = "html" | "markdown" | "plain-text";

export interface ArtifactPreviewResult {
  artifact: TaskRunArtifact;
  artifacts: TaskRunArtifact[];
  preview: PreviewData;
  source?: string;
}

function extension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

export function editableArtifactKind(
  artifact: TaskRunArtifact,
): EditableArtifactKind | null {
  const contentType = artifact.content_type
    ?.split(";")[0]
    ?.trim()
    .toLowerCase();
  if (contentType === "text/markdown") return "markdown";
  if (contentType === "text/html") return "html";
  if (contentType === "text/plain") return "plain-text";
  if (contentType) return null;

  if (extension(artifact.name) === "md") return "markdown";
  if (extension(artifact.name) === "html") return "html";
  if (extension(artifact.name) === "txt") return "plain-text";
  return null;
}

export function newestUndismissedVersion(
  artifacts: TaskRunArtifact[],
  name: string,
): TaskRunArtifact | undefined {
  const group = groupRunArtifactVersions(artifacts).find(
    (candidate) => candidate.name === name,
  );
  return group?.versions.find((version) => !version.dismissed_at);
}

export function editorFilePath(
  kind: EditableArtifactKind,
  name: string,
): string {
  const expectedExtension =
    kind === "markdown" ? "md" : kind === "html" ? "html" : "txt";
  return extension(name) === expectedExtension
    ? name
    : `artifact.${expectedExtension}`;
}

function isArtifactPreviewResult(
  data: PreviewData | ArtifactPreviewResult | undefined,
): data is ArtifactPreviewResult {
  return Boolean(data && typeof data === "object" && "preview" in data);
}

export function useArtifactPreviewData({
  sessionService,
  authIdentity,
  taskId,
  runId,
  artifactId,
  name,
}: {
  sessionService: SessionService;
  authIdentity: string | null;
  taskId: string;
  runId: string;
  artifactId: string;
  name: string;
}): {
  artifactResult: ArtifactPreviewResult | undefined;
  previewData: PreviewData | undefined;
  previewUrl: string | null;
  isLoading: boolean;
  isError: boolean;
  isPlaceholderData: boolean;
} {
  const { data, isLoading, isError, isPlaceholderData } = useQuery<
    PreviewData | ArtifactPreviewResult
  >({
    queryKey: [
      "artifactPreview",
      authIdentity,
      taskId,
      name,
      runId,
      artifactId,
    ],
    queryFn: async () => {
      // The parallel pair shares one in-flight manifest read; a reference
      // artifact resolves to a null URL there without a presign, so checking
      // its metadata after the pair costs no extra request.
      const [artifacts, url] = await Promise.all([
        sessionService.getCloudRunArtifacts(taskId, runId),
        sessionService.getCloudAttachmentPreviewUrl(taskId, runId, artifactId),
      ]);
      const artifact = artifacts.find(
        (candidate) => candidate.id === artifactId,
      );
      if (!artifact) throw new Error("Artifact is unavailable");
      const reference = getPostHogObjectArtifactMetadata(artifact);
      if (reference) {
        return {
          artifact,
          artifacts,
          preview: { kind: "posthog-object", metadata: reference },
        };
      }
      if (!url) throw new Error("Artifact is unavailable");
      const response = await fetch(url);
      if (!response.ok) throw new Error("Artifact preview failed");
      const blob = await response.blob();
      const fileExtension = extension(name);
      const editableKind = editableArtifactKind(artifact);
      const needsSource =
        editableKind !== null || MARKDOWN_EXTENSIONS.has(fileExtension);
      const source = needsSource ? await blob.text() : undefined;
      let preview: PreviewData;
      if (
        editableKind === "markdown" ||
        MARKDOWN_EXTENSIONS.has(fileExtension)
      ) {
        preview = source ?? "";
      } else if (
        editableKind === "html" ||
        HTML_EXTENSIONS.has(fileExtension)
      ) {
        preview = { kind: "html", html: source ?? (await blob.text()) };
      } else {
        preview = await artifactPreviewBlob(blob, name);
      }
      return {
        artifact,
        artifacts,
        preview,
        ...(source === undefined ? {} : { source }),
      };
    },
    enabled: authIdentity !== null,
    staleTime: Infinity,
    placeholderData: (previousData, previousQuery) =>
      previousQuery?.queryKey[1] === authIdentity &&
      previousQuery.queryKey[2] === taskId &&
      previousQuery.queryKey[3] === name
        ? previousData
        : undefined,
    retry: false,
    meta: AUTH_SCOPED_QUERY_META,
  });
  const artifactResult = isArtifactPreviewResult(data) ? data : undefined;
  const previewData: PreviewData | undefined = artifactResult
    ? artifactResult.preview
    : (data as PreviewData | undefined);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!(previewData instanceof Blob)) {
      setPreviewUrl(null);
      return;
    }
    const objectUrl = URL.createObjectURL(previewData);
    setPreviewUrl(objectUrl);
    return () => URL.revokeObjectURL(objectUrl);
  }, [previewData]);

  return {
    artifactResult,
    previewData,
    previewUrl,
    isLoading,
    isError,
    isPlaceholderData,
  };
}
