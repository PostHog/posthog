import { LoopIcon } from "@posthog/ui/primitives/LoopIcon";
import { Flex, Text } from "@radix-ui/themes";

/**
 * Header lockup for a loop with no space to walk back to — a project-level
 * loop, or any loop while the spaces layout is off. Names the scene without
 * pretending there's a parent to click.
 *
 * A space-attached loop uses {@link LoopSpaceBreadcrumb} instead.
 */
export function LoopHeaderTitle({ label }: { label: string }) {
  return (
    <Flex align="center" gap="2" className="group w-full min-w-0">
      <LoopIcon size={12} className="shrink-0 text-gray-10" />
      <Text
        className="truncate whitespace-nowrap font-medium text-[13px]"
        title={label}
      >
        {label}
      </Text>
    </Flex>
  );
}
