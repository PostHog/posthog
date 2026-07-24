import { CaretRightIcon, ClockIcon } from "@phosphor-icons/react";
import type { ScoutScratchpadEntry } from "@posthog/api-client/posthog-client";
import { splitScratchpadKey } from "@posthog/core/scouts/scoutScratchpad";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Badge, type BadgeProps, Box, Flex, Text } from "@radix-ui/themes";
import { useState } from "react";

// The key prefix (everything before the first colon) encodes the note's *kind* —
// what the scout was doing when it wrote it. Surface it as a colored tag so the
// list scans at a glance.
const KIND_TAG_COLOR: Record<string, BadgeProps["color"]> = {
  pattern: "iris",
  dedupe: "gray",
  noise: "gray",
  baseline: "green",
  watch: "amber",
  watchlist: "amber",
  coverage: "blue",
  emerging: "purple",
  explore: "cyan",
  tags: "cyan",
  recheck: "orange",
};

/**
 * One scratchpad note the scout fleet has written about this project. Shares the
 * collapse/expand grammar of the scout emission cards: a header (chevron · kind ·
 * key · updated time) that stays visible, a 2-line markdown preview when
 * collapsed, the full body plus an attribution footer when open.
 */
export function ScratchpadEntryCard({
  entry,
}: {
  entry: ScoutScratchpadEntry;
}) {
  const [expanded, setExpanded] = useState(false);

  const { kind, body } = splitScratchpadKey(entry.key);

  return (
    <Box className="min-w-0 overflow-hidden rounded-(--radius-2) border border-(--gray-6) bg-gray-1">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full select-none items-center gap-2 px-3 py-2 text-left"
      >
        <CaretRightIcon
          size={11}
          className={`shrink-0 text-gray-9 transition-transform duration-150 ${expanded ? "rotate-90" : ""}`}
        />
        {kind ? (
          <Badge
            variant="soft"
            color={KIND_TAG_COLOR[kind] ?? "gray"}
            size="1"
            className="shrink-0 text-[11px]"
          >
            {kind}
          </Badge>
        ) : null}
        <Text className="truncate font-mono text-[12px] text-gray-12">
          {body}
        </Text>
        <span className="flex-1" />
        {entry.updated_at ? (
          <Flex align="center" gap="1" className="shrink-0 text-gray-10">
            <ClockIcon size={11} className="text-gray-9" />
            <RelativeTimestamp timestamp={entry.updated_at} />
          </Flex>
        ) : null}
      </button>

      <Box className="px-3 pb-2 pl-9">
        <Box
          className={`text-pretty break-words text-[13px] text-gray-11 leading-relaxed [&_code]:text-[11px] [&_p:last-child]:mb-0 [&_p]:mb-1 [&_pre]:text-[11px] ${
            expanded ? "" : "line-clamp-2"
          }`}
        >
          <MarkdownRenderer content={entry.content || "_No content._"} />
        </Box>

        {expanded && entry.created_at ? (
          <Flex
            align="center"
            gap="2"
            mt="2"
            pt="2"
            wrap="wrap"
            className="border-t border-t-(--gray-5) text-[11px] text-gray-10"
          >
            <Text className="text-[11px] text-gray-10">Created</Text>
            <RelativeTimestamp timestamp={entry.created_at} />
          </Flex>
        ) : null}
      </Box>
    </Box>
  );
}
