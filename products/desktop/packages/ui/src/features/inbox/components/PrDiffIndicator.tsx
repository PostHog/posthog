import { Flex, Text, Tooltip } from "@radix-ui/themes";

export interface PrDiffIndicatorProps {
  added: number;
  removed: number;
  files?: number;
  className?: string;
}

export function hasVisibleDiffStats(added: number, removed: number): boolean {
  return added > 0 || removed > 0;
}

export function PrDiffIndicator({
  added,
  removed,
  files,
  className = "",
}: PrDiffIndicatorProps) {
  if (!hasVisibleDiffStats(added, removed)) {
    return null;
  }

  const fileLabel =
    files != null
      ? `${files} file${files === 1 ? "" : "s"} changed`
      : undefined;

  const indicator = (
    <Flex
      align="center"
      gap="1.5"
      className={`shrink-0 font-mono text-[12px] tabular-nums ${className}`}
    >
      {added > 0 && (
        <Text className="font-medium text-(--green-11)">+{added}</Text>
      )}
      {removed > 0 && (
        <Text className="font-medium text-(--red-11)">−{removed}</Text>
      )}
    </Flex>
  );

  if (!fileLabel) {
    return indicator;
  }

  return <Tooltip content={fileLabel}>{indicator}</Tooltip>;
}
