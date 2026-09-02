import { GitDiff } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { Flex, Text } from "@radix-ui/themes";

export interface DiffStatsBadgeProps {
  filesChanged: number;
  linesAdded: number;
  linesRemoved: number;
  active?: boolean;
  onClick?: () => void;
}

export function DiffStatsBadge({
  filesChanged,
  linesAdded,
  linesRemoved,
  active = false,
  onClick,
}: DiffStatsBadgeProps) {
  const hasChanges = filesChanged > 0;
  return (
    <Button
      onClick={onClick}
      variant="outline"
      size="sm"
      className={`no-drag font-mono text-(--gray-11) text-[11px] transition-colors duration-100 hover:bg-(--gray-a3) ${active ? "bg-(--gray-a3)" : "bg-transparent"}`}
    >
      <GitDiff size={14} className="shrink-0" />
      {hasChanges ? (
        <Flex align="center" gap="1">
          {linesAdded > 0 && (
            <Text className="text-(--green-9) text-[11px]">+{linesAdded}</Text>
          )}
          {linesRemoved > 0 && (
            <Text className="text-(--red-9) text-[11px]">-{linesRemoved}</Text>
          )}
        </Flex>
      ) : (
        <Text className="text-(--gray-9) text-[11px]">0</Text>
      )}
    </Button>
  );
}
