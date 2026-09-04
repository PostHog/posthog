import { getRelativePath } from "@posthog/core/code-editor/pathUtils";
import { isAbsolutePath } from "@posthog/shared";
import { Flex, Text } from "@radix-ui/themes";
import { memo, useCallback } from "react";
import { FileIcon } from "../../../../primitives/FileIcon";
import { useFileLinkOpener } from "../../../code-editor/useFileLinkOpener";
import { useCwd } from "../../../sidebar/useCwd";
import { useWorkspace } from "../../../workspace/useWorkspace";
import { useSessionTaskId } from "../../useSessionTaskId";
import { useFileContextMenu } from "../useFileContextMenu";
import { getFilename } from "./toolCallUtils";

interface FileMentionChipProps {
  filePath: string;
}

export const FileMentionChip = memo(function FileMentionChip({
  filePath,
}: FileMentionChipProps) {
  const taskId = useSessionTaskId();
  const repoPath = useCwd(taskId ?? "");
  const workspace = useWorkspace(taskId ?? undefined);
  const openFile = useFileLinkOpener("agent-suggestion");
  const { openForFile } = useFileContextMenu();

  const filename = getFilename(filePath);
  const mainRepoPath = workspace?.folderPath;

  const handleClick = useCallback(() => {
    openFile?.({ path: filePath, line: null });
  }, [openFile, filePath]);

  const handleContextMenu = useCallback(
    async (e: React.MouseEvent) => {
      e.preventDefault();
      const absolutePath = isAbsolutePath(filePath)
        ? filePath
        : repoPath
          ? `${repoPath}/${filePath}`
          : filePath;

      await openForFile({
        absolutePath,
        filename,
        workspace,
        mainRepoPath,
      });
    },
    [filePath, repoPath, filename, workspace, mainRepoPath, openForFile],
  );

  const isClickable = !!openFile;

  const relativePath = getRelativePath(filePath, repoPath);
  const directory =
    relativePath && relativePath !== filename
      ? relativePath.replace(`/${filename}`, "")
      : null;

  return (
    <Flex
      align="center"
      gap="1"
      asChild
      onClick={isClickable ? handleClick : undefined}
      onContextMenu={handleContextMenu}
      className={`relative top-[1px] inline-flex min-w-0 max-w-full ${isClickable ? "cursor-pointer hover:underline" : ""}`}
    >
      <Text className="text-[13px]">
        <FileIcon filename={filename} size={12} />
        <span className="flex min-w-0 flex-1 items-baseline gap-1 overflow-hidden font-mono text-[13px] leading-none">
          {/* The lopsided shrink factor on the directory below makes it give way
              first, so the filename only ellipsizes once there is no room for it
              either. */}
          <span className="min-w-0 truncate font-semibold">{filename}</span>
          {directory && (
            <span className="min-w-0 shrink-[9999] overflow-hidden text-ellipsis whitespace-nowrap text-muted-foreground/50">
              {directory}
            </span>
          )}
        </span>
      </Text>
    </Flex>
  );
});
