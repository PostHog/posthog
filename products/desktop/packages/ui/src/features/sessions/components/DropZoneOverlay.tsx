import { FileArrowUp } from "@phosphor-icons/react";
import { Flex, Text } from "@radix-ui/themes";

interface DropZoneOverlayProps {
  isVisible: boolean;
}

export function DropZoneOverlay({ isVisible }: DropZoneOverlayProps) {
  if (!isVisible) return null;

  return (
    <Flex
      position="absolute"
      inset="0"
      align="center"
      justify="center"
      className="pointer-events-none z-50 m-[8px] rounded-(--radius-3) bg-(--color-background) opacity-90"
      style={{
        border: "2px dashed var(--accent-8)",
      }}
    >
      <Flex direction="column" align="center" gap="2">
        <FileArrowUp size={32} weight="duotone" className="text-accent-11" />
        <Text className="font-medium text-accent-11 text-sm">
          Drop files to attach
        </Text>
      </Flex>
    </Flex>
  );
}
