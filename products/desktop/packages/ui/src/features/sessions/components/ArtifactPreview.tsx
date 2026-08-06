import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { Spinner } from "@posthog/quill";
import { isAllowedImageMimeType } from "@posthog/shared";
import {
  getAuthIdentity,
  useAuthStateValue,
} from "@posthog/ui/features/auth/store";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { Flex } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { ZoomableImage } from "../../../primitives/SafeImagePreview";
import { CodeMirrorEditor } from "../../code-editor/components/CodeMirrorEditor";
import { DocumentPreviewHeader } from "../../code-editor/components/DocumentPreviewHeader";
import { MarkdownDocumentPreview } from "../../code-editor/components/MarkdownDocumentPreview";
import { artifactPreviewBlob } from "./artifactPreviewDocument";

const MARKDOWN_EXTENSIONS = new Set(["md", "mdx", "markdown"]);

function extension(filename: string): string {
  return filename.split(".").pop()?.toLowerCase() ?? "";
}

function ArtifactPreviewError() {
  return (
    <div className="flex h-full items-center justify-center text-muted-foreground">
      This artifact can’t be previewed.
    </div>
  );
}

function ArtifactImagePreview({ src, name }: { src: string; name: string }) {
  const [hasError, setHasError] = useState(false);

  if (hasError) return <ArtifactPreviewError />;
  return (
    <ZoomableImage
      src={src}
      alt={name}
      controls
      className="size-full bg-(--gray-2) p-4"
      onError={() => setHasError(true)}
    />
  );
}

export function ArtifactPreview({
  taskId,
  runId,
  artifactId,
  name,
}: {
  taskId: string;
  runId: string;
  artifactId: string;
  name: string;
}) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const [showRendered, setShowRendered] = useState(true);
  const authIdentity = useAuthStateValue(getAuthIdentity);
  const { data, isLoading, isError } = useQuery({
    queryKey: ["artifactPreview", authIdentity, taskId, runId, artifactId],
    queryFn: async () => {
      const url = await sessionService.getCloudAttachmentPreviewUrl(
        taskId,
        runId,
        artifactId,
      );
      if (!url) throw new Error("Artifact is unavailable");
      const response = await fetch(url);
      if (!response.ok) throw new Error("Artifact preview failed");
      const blob = await response.blob();
      if (MARKDOWN_EXTENSIONS.has(extension(name))) {
        return blob.text();
      }
      return artifactPreviewBlob(blob, name);
    },
    enabled: authIdentity !== null,
    staleTime: Infinity,
    retry: false,
    meta: AUTH_SCOPED_QUERY_META,
  });
  const previewUrl = useMemo(
    () => (data instanceof Blob ? URL.createObjectURL(data) : null),
    [data],
  );

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (typeof data === "string") {
    return (
      <Flex direction="column" height="100%" className="overflow-hidden">
        <DocumentPreviewHeader
          label={name}
          content={data}
          showRendered={showRendered}
          onToggleRendered={() => setShowRendered((rendered) => !rendered)}
        />
        {showRendered ? (
          <div className="flex-1 overflow-auto">
            <MarkdownDocumentPreview
              content={data}
              components={{ img: () => null }}
            />
          </div>
        ) : (
          <div className="flex-1 overflow-hidden">
            <CodeMirrorEditor content={data} filePath={name} readOnly />
          </div>
        )}
      </Flex>
    );
  }
  if (isError || !previewUrl) {
    return <ArtifactPreviewError />;
  }
  if (data && isAllowedImageMimeType(data.type)) {
    return <ArtifactImagePreview src={previewUrl} name={name} />;
  }
  return (
    <iframe
      className="h-full w-full border-0 bg-white"
      sandbox=""
      src={previewUrl}
      title={`Preview of ${name}`}
    />
  );
}
