import { EditorView } from "@codemirror/view";
import { MultiFileDiff } from "@pierre/diffs/react";
import { compactHomePath, parseImageDataUrl } from "@posthog/shared";
import { DIFFS_HIGHLIGHTER_OPTIONS } from "@posthog/ui/features/sessions/diffHighlighterOptions";
import { Code } from "@radix-ui/themes";
import { useEffect, useMemo, useRef } from "react";
import { SafeImagePreview } from "../../../../primitives/SafeImagePreview";
import { useThemeStore } from "../../../../shell/themeStore";
import {
  CODE_PREVIEW_CONTAINER_STYLE,
  CODE_PREVIEW_EDITOR_STYLE,
  CODE_PREVIEW_PATH_STYLE,
  useCodePreviewExtensions,
} from "./useCodePreviewExtensions";

interface CodePreviewProps {
  content: string;
  filePath?: string;
  showPath?: boolean;
  oldContent?: string | null;
  firstLineNumber?: number;
  maxHeight?: string;
  cacheKey?: string;
}

export function CodePreview({
  content,
  filePath,
  showPath = false,
  oldContent,
  firstLineNumber = 1,
  maxHeight,
  cacheKey,
}: CodePreviewProps) {
  const isDiff = oldContent !== undefined && oldContent !== null;
  const imageDataUrl = useMemo(
    () => (isDiff ? null : parseImageDataUrl(content)),
    [isDiff, content],
  );

  if (isDiff) {
    return (
      <DiffPreview
        content={content}
        filePath={filePath}
        showPath={showPath}
        oldContent={oldContent}
        maxHeight={maxHeight}
        cacheKey={cacheKey}
      />
    );
  }

  if (imageDataUrl) {
    return (
      <ImageDataUrlPreview
        filePath={filePath}
        showPath={showPath}
        mimeType={imageDataUrl.mimeType}
        base64={imageDataUrl.base64}
        maxHeight={maxHeight}
      />
    );
  }

  return (
    <PlainCodePreview
      content={content}
      filePath={filePath}
      showPath={showPath}
      firstLineNumber={firstLineNumber}
      maxHeight={maxHeight}
    />
  );
}

function ImageDataUrlPreview({
  filePath,
  showPath,
  mimeType,
  base64,
  maxHeight,
}: {
  filePath?: string;
  showPath?: boolean;
  mimeType: string;
  base64: string;
  maxHeight?: string;
}) {
  return (
    <div style={CODE_PREVIEW_CONTAINER_STYLE}>
      {showPath && filePath && (
        <div style={CODE_PREVIEW_PATH_STYLE} title={filePath}>
          <Code variant="ghost" className="truncate text-[13px]">
            {compactHomePath(filePath)}
          </Code>
        </div>
      )}
      <div
        className="flex items-center justify-center bg-(--gray-2) p-2"
        style={maxHeight ? { maxHeight, overflow: "auto" } : undefined}
      >
        <SafeImagePreview
          base64={base64}
          mimeType={mimeType}
          alt={filePath ?? "Image preview"}
          className="max-h-96 max-w-full object-contain"
        />
      </div>
    </div>
  );
}

function DiffPreview({
  content,
  filePath,
  showPath,
  oldContent,
  maxHeight,
  cacheKey,
}: {
  content: string;
  filePath?: string;
  showPath?: boolean;
  oldContent: string;
  maxHeight?: string;
  cacheKey?: string;
}) {
  const isDarkMode = useThemeStore((s) => s.isDarkMode);
  const fileName = filePath?.split("/").pop() ?? "file";

  const oldFile = useMemo(
    () => ({
      name: fileName,
      contents: oldContent,
      ...(cacheKey ? { cacheKey: `${cacheKey}:old` } : {}),
    }),
    [fileName, oldContent, cacheKey],
  );
  const newFile = useMemo(
    () => ({
      name: fileName,
      contents: content,
      ...(cacheKey ? { cacheKey: `${cacheKey}:new` } : {}),
    }),
    [fileName, content, cacheKey],
  );
  const options = useMemo(
    () => ({
      ...DIFFS_HIGHLIGHTER_OPTIONS,
      diffStyle: "unified" as const,
      overflow: "wrap" as const,
      themeType: (isDarkMode ? "dark" : "light") as "dark" | "light",
      disableFileHeader: true,
    }),
    [isDarkMode],
  );

  return (
    <div style={CODE_PREVIEW_CONTAINER_STYLE}>
      {showPath && filePath && (
        <div
          style={CODE_PREVIEW_PATH_STYLE}
          className="scroll-mask-2"
          title={filePath}
        >
          <Code variant="ghost" className="truncate text-[13px]">
            {compactHomePath(filePath)}
          </Code>
        </div>
      )}
      <div
        className="scroll-mask-2"
        style={maxHeight ? { maxHeight, overflow: "auto" } : undefined}
      >
        <MultiFileDiff oldFile={oldFile} newFile={newFile} options={options} />
      </div>
    </div>
  );
}

function PlainCodePreview({
  content,
  filePath,
  showPath,
  firstLineNumber,
  maxHeight,
}: {
  content: string;
  filePath?: string;
  showPath?: boolean;
  firstLineNumber: number;
  maxHeight?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<EditorView | null>(null);
  const extensions = useCodePreviewExtensions(filePath, firstLineNumber);

  useEffect(() => {
    if (!containerRef.current) return;

    editorRef.current?.destroy();

    editorRef.current = new EditorView({
      doc: content,
      extensions,
      parent: containerRef.current,
    });

    return () => {
      editorRef.current?.destroy();
      editorRef.current = null;
    };
  }, [content, extensions]);

  return (
    <div style={CODE_PREVIEW_CONTAINER_STYLE}>
      {showPath && filePath && (
        <div style={CODE_PREVIEW_PATH_STYLE} title={filePath}>
          <Code variant="ghost" className="truncate text-[13px]">
            {compactHomePath(filePath)}
          </Code>
        </div>
      )}
      <div
        ref={containerRef}
        style={
          maxHeight
            ? { ...CODE_PREVIEW_EDITOR_STYLE, maxHeight }
            : CODE_PREVIEW_EDITOR_STYLE
        }
      />
    </div>
  );
}
