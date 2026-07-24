import { Warning } from "@phosphor-icons/react";
import { GitDialog } from "@posthog/ui/features/git-interaction/components/GitInteractionDialogs";
import {
  getStatusIndicator,
  type StatusIndicator,
} from "@posthog/ui/features/git-interaction/utils/gitStatusUtils";
import type { HandoffChangedFile } from "@posthog/ui/features/sessions/handoffDialogStore";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";

interface DirtyTreeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  changedFiles: HandoffChangedFile[];
  onCommitAndContinue: () => void;
}

function FileLineStats({ file }: { file: HandoffChangedFile }) {
  const hasStats =
    file.linesAdded !== undefined || file.linesRemoved !== undefined;
  if (!hasStats) return null;

  return (
    <Flex
      align="center"
      gap="1"
      className="shrink-0 font-mono text-[10px] leading-none"
    >
      {(file.linesAdded ?? 0) > 0 && (
        <Text className="text-(--green-9)">+{file.linesAdded}</Text>
      )}
      {(file.linesRemoved ?? 0) > 0 && (
        <Text className="text-(--red-9)">-{file.linesRemoved}</Text>
      )}
    </Flex>
  );
}

function StatusBadge({ indicator }: { indicator: StatusIndicator }) {
  return (
    <Badge
      size="1"
      color={indicator.color}
      className="shrink-0 px-[4px] py-0 text-[10px]"
    >
      {indicator.label}
    </Badge>
  );
}

export function DirtyTreeDialog({
  open,
  onOpenChange,
  changedFiles,
  onCommitAndContinue,
}: DirtyTreeDialogProps) {
  return (
    <GitDialog
      open={open}
      onOpenChange={onOpenChange}
      icon={<Warning size={14} weight="fill" color="var(--amber-9)" />}
      title="Uncommitted changes"
      error={null}
      buttonLabel="Commit and continue"
      isSubmitting={false}
      onSubmit={onCommitAndContinue}
    >
      <Flex direction="column" gap="2">
        <Text color="gray" className="text-[13px]">
          The following local files have uncommitted changes that would be
          overwritten by the handoff. Commit them to continue.
        </Text>
        <Box className="max-h-[200px] overflow-auto rounded-(--radius-2) border border-(--gray-6)">
          {changedFiles.map((file) => {
            const fileName = file.path.split("/").pop() || file.path;
            const indicator = getStatusIndicator(file.status);
            return (
              <Flex
                key={file.path}
                align="center"
                gap="1"
                px="2"
                className="h-[28px]"
              >
                <FileIcon filename={fileName} size={14} />
                <span className="ml-[4px] min-w-0 flex-1 select-none overflow-hidden text-ellipsis whitespace-nowrap text-[13px]">
                  {fileName}
                </span>
                <FileLineStats file={file} />
                <StatusBadge indicator={indicator} />
              </Flex>
            );
          })}
        </Box>
      </Flex>
    </GitDialog>
  );
}
