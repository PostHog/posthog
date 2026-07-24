import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import {
  SelectionCommentOverlay,
  useSelectionComposer,
} from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import { useRepoFileContent } from "@posthog/ui/features/code-editor/hooks/useFileContent";
import { useFileSearchStore } from "@posthog/ui/features/command/fileSearchStore";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { Cross2Icon } from "@radix-ui/react-icons";
import { Box, Flex, IconButton, Text } from "@radix-ui/themes";

interface NewTaskFilePreviewProps {
  repoPath: string;
  filePath: string;
  onAddSelection?: (startLine: number, endLine: number, text: string) => void;
}

/** Inline read-only file view shown beside the prompt on the new-task screen. */
export function NewTaskFilePreview({
  repoPath,
  filePath,
  onAddSelection,
}: NewTaskFilePreviewProps) {
  const close = useFileSearchStore((state) => state.closePreview);
  const { data: content, isLoading } = useRepoFileContent(
    repoPath,
    filePath,
    true,
  );
  const composer = useSelectionComposer();
  const name = filePath.split("/").pop() ?? filePath;

  return (
    <Flex direction="column" className="h-full min-w-0 overflow-hidden">
      <Flex align="center" gap="2" className="border-gray-4 border-b px-3 py-2">
        <FileIcon filename={name} size={14} />
        <Text size="2" weight="medium" className="truncate">
          {name}
        </Text>
        <Text size="1" className="truncate text-gray-9">
          {filePath}
        </Text>
        <IconButton
          size="1"
          variant="ghost"
          color="gray"
          className="ml-auto"
          aria-label="Close file"
          onClick={close}
        >
          <Cross2Icon />
        </IconButton>
      </Flex>
      <Box className="min-h-0 flex-1 overflow-hidden">
        {isLoading ? (
          <Flex align="center" justify="center" className="h-full">
            <Text size="2" className="text-gray-9">
              Loading…
            </Text>
          </Flex>
        ) : content == null ? (
          <Flex align="center" justify="center" className="h-full">
            <Text size="2" className="text-gray-9">
              File not found
            </Text>
          </Flex>
        ) : (
          <CodeMirrorEditor
            content={content}
            filePath={filePath}
            readOnly
            highlightSelectedLines
            onSelectionChange={composer.onSelectionChange}
          />
        )}
      </Box>
      <SelectionCommentOverlay
        selection={composer.selection}
        open={composer.open && !!onAddSelection}
        filePath={filePath}
        onSubmit={(start, end, text) => onAddSelection?.(start, end, text)}
        onDismiss={composer.close}
      />
    </Flex>
  );
}
