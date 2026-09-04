import type { KeyboardEvent, ReactNode } from "react";
import { useCallback, useMemo } from "react";
import { Tooltip } from "../../../../primitives/Tooltip";
import { usePendingScrollStore } from "../../../code-editor/pendingScrollStore";
import { usePanelLayoutStore } from "../../../panels/panelLayoutStore";
import type { FileItem } from "../../../repo-files/useRepoFiles";
import { useRepoFiles } from "../../../repo-files/useRepoFiles";
import { useCwd } from "../../../sidebar/useCwd";
import { useSessionTaskId } from "../../useSessionTaskId";

const FILE_WITH_DIR_RE =
  /^(?:\/|\.\.?\/|[a-zA-Z]:\\)?(?:[\w.@-]+\/)+[\w.@-]+\.\w+(?::\d+(?:-\d+)?)?$/;
const BARE_FILE_RE = /^[\w.@-]+\.\w+(?::\d+(?:-\d+)?)?$/;

export function hasDirectoryPath(text: string): boolean {
  return FILE_WITH_DIR_RE.test(text);
}

export function looksLikeBareFilename(text: string): boolean {
  return BARE_FILE_RE.test(text);
}

function parseFilePath(text: string): { filePath: string; lineSuffix: string } {
  const match = text.match(/^(.+?)(?::(\d+(?:-\d+)?))?$/);
  if (!match) return { filePath: text, lineSuffix: "" };
  return { filePath: match[1], lineSuffix: match[2] ?? "" };
}

function resolveFilename(filename: string, files: FileItem[]): FileItem | null {
  const matches = files.filter((f) => f.name === filename);
  if (matches.length === 1) return matches[0];
  return null;
}

export function InlineFileLink({
  text,
  resolvedPath,
}: {
  text: string;
  resolvedPath?: string;
}) {
  const { filePath: rawPath, lineSuffix } = parseFilePath(text);
  const filePath = resolvedPath ?? rawPath;
  const filename = rawPath.split("/").pop() ?? rawPath;
  const taskId = useSessionTaskId();
  const repoPath = useCwd(taskId ?? "");
  const openFileInSplit = usePanelLayoutStore((s) => s.openFileInSplit);
  const requestScroll = usePendingScrollStore((s) => s.requestScroll);

  const handleClick = useCallback(() => {
    if (!taskId) return;
    const relativePath =
      repoPath && filePath.startsWith(`${repoPath}/`)
        ? filePath.slice(repoPath.length + 1)
        : filePath;
    const absolutePath = repoPath
      ? `${repoPath}/${relativePath}`
      : relativePath;
    if (lineSuffix) {
      const line = Number.parseInt(lineSuffix.split("-")[0], 10);
      if (line > 0) requestScroll(absolutePath, line);
    }
    openFileInSplit(taskId, relativePath, true);
  }, [taskId, filePath, lineSuffix, repoPath, openFileInSplit, requestScroll]);

  const tooltipText = resolvedPath ?? text;

  // A <span>, not a <button>: Chromium leaves <button> text out of document
  // selections, so copying chat output that contains these chips dropped every
  // file reference from the pasted text.
  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLSpanElement>) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        handleClick();
      }
    },
    [handleClick],
  );

  return (
    <Tooltip content={tooltipText}>
      {/* biome-ignore lint/a11y/useSemanticElements: a <button> is not selectable in Chromium, which breaks copy of selected chat text */}
      <span
        role="button"
        tabIndex={taskId ? 0 : undefined}
        onClick={taskId ? handleClick : undefined}
        onKeyDown={taskId ? handleKeyDown : undefined}
        aria-disabled={taskId ? undefined : true}
        className={`m-0 inline border-0 bg-transparent p-0 font-[inherit] text-[length:inherit] text-foreground outline-none focus-visible:underline ${taskId ? "cursor-pointer underline underline-offset-2" : ""}`}
      >
        {filename}
        {lineSuffix ? `:${lineSuffix}` : ""}
      </span>
    </Tooltip>
  );
}

export function BareFileLink({
  text,
  fallback,
}: {
  text: string;
  fallback: ReactNode;
}) {
  const { filePath: bareFilename } = parseFilePath(text);
  const taskId = useSessionTaskId();
  const repoPath = useCwd(taskId ?? "");
  const { files } = useRepoFiles(repoPath ?? undefined);
  const resolved = useMemo(
    () => resolveFilename(bareFilename, files),
    [bareFilename, files],
  );

  if (!resolved) return <>{fallback}</>;
  return <InlineFileLink text={text} resolvedPath={resolved.path} />;
}
