import { ArrowRightIcon, NotebookIcon } from "@phosphor-icons/react";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import { useScoutScratchpad } from "../hooks/useScoutScratchpad";

/**
 * Scratchpad stat card for the scout fleet section. Surfaces that the scouts
 * have jotted down context about this project — count + recency hint at what
 * they're picking up — and links into the full scratchpad browse/search surface.
 * Renders nothing until there is at least one note, so a fresh project isn't
 * nudged toward an empty page.
 */
export function FleetMemoryCallout() {
  const { data: entries } = useScoutScratchpad();

  // Hold until the first load settles, then only show when there's something to
  // read. Entries arrive newest-first, so the head drives the "updated" hint.
  if (!entries || entries.length === 0) {
    return null;
  }

  const totalCount = entries.length;
  const lastUpdatedAt = entries[0]?.updated_at ?? null;

  return (
    <Link
      to="/code/agents/scouts/scratchpad"
      className="flex w-full items-center gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5 text-left no-underline transition-colors duration-150 hover:border-(--gray-6) hover:bg-(--gray-2)"
    >
      <NotebookIcon size={20} className="shrink-0 text-(--iris-9)" />
      <Flex direction="column" className="min-w-0">
        <Text className="font-medium text-[13px] text-gray-12">
          Scout scratchpad
        </Text>
        <Text className="truncate text-[12px] text-gray-11 leading-snug">
          {totalCount} note{totalCount === 1 ? "" : "s"} your scouts have jotted
          down about this project
          {lastUpdatedAt ? (
            <>
              {" · updated "}
              <RelativeTimestamp
                timestamp={lastUpdatedAt}
                className="inline text-[12px] text-gray-11"
              />
            </>
          ) : null}
        </Text>
      </Flex>
      <span className="flex-1" />
      <ArrowRightIcon size={14} className="shrink-0 text-gray-10" />
    </Link>
  );
}
