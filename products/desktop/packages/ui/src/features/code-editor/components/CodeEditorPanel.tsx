import { Check, Code, Copy, Eye } from "@phosphor-icons/react";
import { getRenderableKind } from "@posthog/core/code-editor/fileKind";
import {
  collapseFileState,
  resolveMarkdownLink,
  selectFileSource,
} from "@posthog/core/code-editor/fileSource";
import { getRelativePath } from "@posthog/core/code-editor/pathUtils";
import { buildFileLineReferencePrompt } from "@posthog/core/code-review/reviewPrompts";
import { xmlToContent } from "@posthog/core/message-editor/content";
import {
  getImageMimeType,
  isRasterImageFile,
  parseImageDataUrl,
} from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { Box, Flex, IconButton, Text } from "@radix-ui/themes";
import { useCallback, useMemo, useState } from "react";
import type { Components } from "react-markdown";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PanelMessage } from "../../../primitives/PanelMessage";
import { SafeImagePreview } from "../../../primitives/SafeImagePreview";
import { Tooltip } from "../../../primitives/Tooltip";
import { openExternalUrl } from "../../../shell/openExternal";
import { useDraftStore } from "../../message-editor/draftStore";
import { usePanelLayoutStore } from "../../panels/panelLayoutStore";
import { useFileTreeStore } from "../../right-sidebar/fileTreeStore";
import { useCwd } from "../../sidebar/useCwd";
import { useIsWorkspaceCloudRun } from "../../workspace/useWorkspace";
import { useFilePreviewStore } from "../filePreviewStore";
import { useCloudFileContent } from "../hooks/useCloudFileContent";
import {
  useAbsoluteFileContent,
  useFileAsBase64,
  useRepoFileContent,
} from "../hooks/useFileContent";
import { useFileEnrichment } from "../hooks/useFileEnrichment";
import { CodeMirrorEditor } from "./CodeMirrorEditor";
import { EnrichmentPopover } from "./EnrichmentPopover";
import {
  SelectionCommentOverlay,
  useSelectionComposer,
} from "./SelectionCommentOverlay";

interface CodeEditorPanelProps {
  taskId: string;
  task: Task;
  absolutePath: string;
}

function FilePanelImagePreview({
  base64,
  mimeType,
  filePath,
  absolutePath,
}: {
  base64: string;
  mimeType: string;
  filePath: string;
  absolutePath: string;
}) {
  return (
    <Flex
      align="center"
      justify="center"
      height="100%"
      p="4"
      className="overflow-auto"
    >
      <SafeImagePreview
        base64={base64}
        mimeType={mimeType}
        alt={filePath}
        className="max-h-[100%] max-w-[100%] object-contain"
        fallback={
          <PanelMessage detail={absolutePath}>
            Failed to render image
          </PanelMessage>
        }
      />
    </Flex>
  );
}

function HtmlFilePreview({ content }: { content: string }) {
  return (
    <Box className="flex-1 overflow-hidden bg-white">
      {/*
        Render the HTML in a null-origin sandboxed iframe: allow-scripts WITHOUT
        allow-same-origin lets scripts run but keeps the document on a null
        origin, so it cannot reach the host renderer's DOM, cookies, or storage.
        Do not add allow-same-origin — it collapses that isolation boundary.
      */}
      <iframe
        title="HTML preview"
        sandbox="allow-scripts"
        srcDoc={content}
        className="h-full w-full border-0"
      />
    </Box>
  );
}

export function CodeEditorPanel({
  taskId,
  task: _task,
  absolutePath,
}: CodeEditorPanelProps) {
  const repoPath = useCwd(taskId);
  const isInsideRepo = !!repoPath && absolutePath.startsWith(repoPath);
  const filePath = getRelativePath(absolutePath, repoPath);
  const isImage = isRasterImageFile(absolutePath);
  const renderableKind = getRenderableKind(absolutePath);
  const isRenderable = renderableKind !== null;
  const showRendered = useFilePreviewStore((s) =>
    renderableKind ? s.renderPreview[renderableKind] : false,
  );
  const toggleKind = useFilePreviewStore((s) => s.toggleKind);
  const openFileInSplit = usePanelLayoutStore((s) => s.openFileInSplit);
  const expandToFile = useFileTreeStore((s) => s.expandToFile);
  const [copied, setCopied] = useState(false);

  const composer = useSelectionComposer();
  const handleAddSelectionToChat = useCallback(
    (startLine: number, endLine: number, text: string) => {
      const prompt = buildFileLineReferencePrompt(
        absolutePath,
        startLine,
        endLine,
        text,
      );
      // sessionId === taskId for the in-task chat composer.
      useDraftStore
        .getState()
        .actions.insertPendingContent(taskId, xmlToContent(prompt));
    },
    [absolutePath, taskId],
  );

  const handleMarkdownLinkClick = useCallback(
    (e: React.MouseEvent<HTMLAnchorElement>, href: string) => {
      e.preventDefault();
      const link = resolveMarkdownLink(href, filePath, repoPath);
      if (link.kind === "external") {
        openExternalUrl(link.href);
        return;
      }
      if (link.absolutePath) {
        expandToFile(taskId, link.absolutePath);
      }
      if (link.relativePath) {
        openFileInSplit(taskId, link.relativePath);
      }
    },
    [filePath, taskId, repoPath, openFileInSplit, expandToFile],
  );

  const markdownComponents: Components = useMemo(
    () => ({
      a: ({ href, children }) => (
        <Tooltip content={href ?? ""}>
          <a
            href={href ?? "#"}
            onClick={(e) => handleMarkdownLinkClick(e, href ?? "")}
            className="cursor-pointer text-(--accent-11) underline"
          >
            {children}
          </a>
        </Tooltip>
      ),
    }),
    [handleMarkdownLinkClick],
  );

  const isCloudRun = useIsWorkspaceCloudRun(taskId);
  const source = selectFileSource({ isInsideRepo, isCloudRun, isImage });

  const cloudFile = useCloudFileContent(taskId, filePath, source.cloudEnabled);
  const repoQuery = useRepoFileContent(
    repoPath ?? "",
    filePath,
    source.repoEnabled,
  );
  const absoluteQuery = useAbsoluteFileContent(
    absolutePath,
    source.absoluteEnabled,
  );
  const imageQuery = useFileAsBase64(absolutePath, source.imageEnabled);

  const localQuery = isInsideRepo ? repoQuery : absoluteQuery;
  const {
    content: fileContent,
    isLoading,
    error,
  } = collapseFileState({
    cloudFile: { content: cloudFile.content, isLoading: cloudFile.isLoading },
    localQuery: {
      content: localQuery.data,
      isLoading: localQuery.isLoading,
      error: localQuery.error,
    },
    isCloudRun,
  });

  const enrichment = useFileEnrichment({
    taskId,
    filePath,
    absolutePath: isInsideRepo ? absolutePath : undefined,
    content: isImage ? null : fileContent,
  });

  const dataUrlImage = useMemo(
    () =>
      isImage || fileContent == null ? null : parseImageDataUrl(fileContent),
    [isImage, fileContent],
  );

  if (isImage) {
    if (isCloudRun) {
      return (
        <PanelMessage detail={filePath}>
          Images not available for cloud runs
        </PanelMessage>
      );
    }
    if (imageQuery.isLoading) {
      return <PanelMessage>Loading image...</PanelMessage>;
    }
    if (imageQuery.error || !imageQuery.data) {
      return (
        <PanelMessage detail={absolutePath}>Failed to load image</PanelMessage>
      );
    }
    return (
      <FilePanelImagePreview
        base64={imageQuery.data}
        mimeType={getImageMimeType(absolutePath)}
        filePath={filePath}
        absolutePath={absolutePath}
      />
    );
  }

  if (isLoading) {
    return <PanelMessage>Loading file...</PanelMessage>;
  }

  if (isCloudRun && !cloudFile.touched) {
    return (
      <PanelMessage detail={filePath}>
        File content not available — the agent did not read or write this file
      </PanelMessage>
    );
  }

  if (isCloudRun && cloudFile.touched && cloudFile.content == null) {
    return (
      <PanelMessage detail={filePath}>
        This file was deleted by the agent
      </PanelMessage>
    );
  }

  if (error || fileContent == null) {
    return (
      <PanelMessage detail={absolutePath}>Failed to load file</PanelMessage>
    );
  }

  if (fileContent.length === 0) {
    return <PanelMessage>File is empty</PanelMessage>;
  }

  if (dataUrlImage) {
    return (
      <FilePanelImagePreview
        base64={dataUrlImage.base64}
        mimeType={dataUrlImage.mimeType}
        filePath={filePath}
        absolutePath={absolutePath}
      />
    );
  }

  const sourceView = (
    <Box height="100%" className="relative overflow-hidden">
      <CodeMirrorEditor
        content={fileContent}
        filePath={absolutePath}
        relativePath={filePath}
        readOnly
        enrichment={enrichment}
        highlightSelectedLines
        onSelectionChange={composer.onSelectionChange}
      />
      <EnrichmentPopover />
      <SelectionCommentOverlay
        selection={composer.selection}
        open={composer.open}
        filePath={filePath}
        onSubmit={handleAddSelectionToChat}
        onDismiss={composer.close}
      />
    </Box>
  );

  if (isRenderable) {
    const handleCopySource = () => {
      navigator.clipboard.writeText(fileContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    };
    const handleToggleRendered = () => {
      if (renderableKind) {
        toggleKind(renderableKind);
      }
    };

    return (
      <Flex direction="column" height="100%" className="overflow-hidden">
        <Flex
          px="3"
          py="2"
          align="center"
          justify="between"
          className="shrink-0 border-b border-b-(--gray-6)"
        >
          <Text
            color="gray"
            className="font-[var(--code-font-family)] text-[13px]"
          >
            {filePath}
          </Text>
          <Flex align="center" gap="1">
            <Tooltip content={showRendered ? "View source" : "View preview"}>
              <IconButton
                size="1"
                variant="ghost"
                color="gray"
                className="cursor-pointer"
                onClick={handleToggleRendered}
                aria-label={showRendered ? "View source" : "View preview"}
              >
                {showRendered ? <Code size={14} /> : <Eye size={14} />}
              </IconButton>
            </Tooltip>
            <Tooltip content={copied ? "Copied" : "Copy source"}>
              <IconButton
                size="1"
                variant="ghost"
                color="gray"
                className="cursor-pointer"
                onClick={handleCopySource}
                aria-label="Copy source"
              >
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </IconButton>
            </Tooltip>
          </Flex>
        </Flex>
        {!showRendered ? (
          <Box className="flex-1 overflow-hidden">{sourceView}</Box>
        ) : renderableKind === "markdown" ? (
          <Box className="flex-1 overflow-auto">
            <Box className="plan-markdown max-w-[750px]" p="5">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={markdownComponents}
              >
                {fileContent}
              </ReactMarkdown>
            </Box>
          </Box>
        ) : (
          <HtmlFilePreview content={fileContent} />
        )}
      </Flex>
    );
  }

  return sourceView;
}
