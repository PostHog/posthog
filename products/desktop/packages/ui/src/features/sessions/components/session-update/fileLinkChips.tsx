import type { ReactNode } from "react";
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

  return (
    <Tooltip content={tooltipText}>
      <button
        type="button"
        onClick={taskId ? handleClick : undefined}
        disabled={!taskId}
        className={`m-0 inline border-0 bg-transparent p-0 font-[inherit] text-(--accent-11) text-[length:inherit] ${taskId ? "cursor-pointer underline decoration-(--accent-a8) underline-offset-2 hover:decoration-(--accent-11)" : ""}`}
      >
        {filename}
        {lineSuffix ? `:${lineSuffix}` : ""}
      </button>
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
