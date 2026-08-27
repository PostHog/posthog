import { getDeferredMessage } from "@posthog/core/code-review/reviewShellGeometry";
import {
  getImageMimeType,
  getVideoMimeType,
  isPlayableVideoFile,
  isRasterImageFile,
} from "@posthog/shared";
import type { ReactNode } from "react";
import { useInView } from "../../../primitives/hooks/useInView";
import { SafeImagePreview } from "../../../primitives/SafeImagePreview";
import { SafeVideoPreview } from "../../../primitives/SafeVideoPreview";
import { useFileAsBase64 } from "../../code-editor/hooks/useFileContent";
import { REVIEW_PREFETCH_ROOT_MARGIN } from "../constants";
import {
  FileHeaderRow,
  OpenFileButton,
  splitFilePath,
} from "../reviewShellParts";

type BinaryMediaKind = "image" | "video" | "other";

function classifyBinaryFile(filePath: string): BinaryMediaKind {
  if (isRasterImageFile(filePath)) return "image";
  if (isPlayableVideoFile(filePath)) return "video";
  return "other";
}

interface BinaryFileDiffProps {
  filePath: string;
  /**
   * Absolute path of the working-tree file to preview. Omit when no local file
   * is available (e.g. branch/PR diffs) — the body falls back to a placeholder.
   */
  absolutePath?: string;
  collapsed: boolean;
  onToggle: () => void;
  onOpenFile?: () => void;
}

function BinaryBodyMessage({ children }: { children: ReactNode }) {
  return (
    <div className="w-full border-b border-b-(--gray-5) bg-(--gray-2) p-[16px] text-center text-(--gray-9) text-xs">
      {children}
    </div>
  );
}

function BinaryMediaBody({
  kind,
  absolutePath,
  filePath,
  enabled,
}: {
  kind: "image" | "video";
  absolutePath: string;
  filePath: string;
  enabled: boolean;
}) {
  const { data, isLoading, error } = useFileAsBase64(absolutePath, enabled);

  if (!enabled || isLoading) {
    return <BinaryBodyMessage>Loading preview…</BinaryBodyMessage>;
  }
  if (error || !data) {
    return (
      <BinaryBodyMessage>{getDeferredMessage("binary")}</BinaryBodyMessage>
    );
  }

  const fallback = (
    <BinaryBodyMessage>{getDeferredMessage("binary")}</BinaryBodyMessage>
  );

  return (
    <div className="flex max-h-[600px] justify-center overflow-auto border-b border-b-(--gray-5) bg-(--gray-2) p-4">
      {kind === "image" ? (
        <SafeImagePreview
          base64={data}
          mimeType={getImageMimeType(filePath)}
          alt={filePath}
          className="max-h-[560px] max-w-full"
          fallback={fallback}
        />
      ) : (
        <SafeVideoPreview
          base64={data}
          mimeType={getVideoMimeType(filePath)}
          label={filePath}
          className="max-h-[560px] max-w-full rounded"
          fallback={fallback}
        />
      )}
    </div>
  );
}

export function BinaryFileDiff({
  filePath,
  absolutePath,
  collapsed,
  onToggle,
  onOpenFile,
}: BinaryFileDiffProps) {
  const kind = classifyBinaryFile(filePath);
  const [containerRef, inView] = useInView<HTMLDivElement>({
    rootMargin: REVIEW_PREFETCH_ROOT_MARGIN,
    once: true,
  });
  const { dirPath, fileName } = splitFilePath(filePath);
  const previewKind = kind === "image" || kind === "video" ? kind : null;

  return (
    <div ref={containerRef}>
      <FileHeaderRow
        dirPath={dirPath}
        fileName={fileName}
        additions={0}
        deletions={0}
        collapsed={collapsed}
        onToggle={onToggle}
        trailing={
          // Only images get an "open" button — the editor panel renders images
          // but would show a video/other binary as garbled text.
          onOpenFile && kind === "image" ? (
            <OpenFileButton onClick={onOpenFile} />
          ) : undefined
        }
      />
      {!collapsed &&
        (previewKind && absolutePath ? (
          <BinaryMediaBody
            kind={previewKind}
            absolutePath={absolutePath}
            filePath={filePath}
            enabled={inView}
          />
        ) : (
          <BinaryBodyMessage>{getDeferredMessage("binary")}</BinaryBodyMessage>
        ))}
    </div>
  );
}
