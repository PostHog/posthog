import type { ReactNode } from "react";
import { useCallback, useMemo } from "react";
import { Tooltip } from "../../../../primitives/Tooltip";
import { useFileLinkOpener } from "../../../code-editor/useFileLinkOpener";
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
  const openFile = useFileLinkOpener("agent-suggestion");

  const line = Number.parseInt(lineSuffix, 10) || null;
  const handleClick = useCallback(() => {
    openFile?.({ path: filePath, line });
  }, [openFile, filePath, line]);

  const label = `${filename}${lineSuffix ? `:${lineSuffix}` : ""}`;
  if (!openFile) return <>{label}</>;

  return (
    <Tooltip content={resolvedPath ?? text}>
      <button
        type="button"
        onClick={handleClick}
        className="m-0 inline cursor-pointer border-0 bg-transparent p-0 font-[inherit] text-[length:inherit] text-foreground underline underline-offset-2"
      >
        {label}
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
