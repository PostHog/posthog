import { CaretRightIcon, CompassIcon } from "@phosphor-icons/react";
import type {
  LinkedSignalReport,
  ScoutEmission,
} from "@posthog/api-client/posthog-client";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { track } from "@posthog/ui/shell/analytics";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { SeverityBadge } from "./ScoutBadges";
import { ScoutLinkedReportChip } from "./ScoutLinkedReportChip";

export function ScoutEmissionCard({
  emission,
  skillName,
  scoutLabel,
  actions,
  footerEnd,
  linkedReport,
  defaultExpanded = false,
  highlighted = false,
}: {
  emission: ScoutEmission;
  /** The emitting scout, attached to analytics events when known. */
  skillName?: string;
  /**
   * Prettified emitting-scout name, shown in the header. Set on cross-fleet
   * surfaces (the findings page) where cards from different scouts are mixed;
   * omit on a single-scout surface where the scout is already obvious.
   */
  scoutLabel?: string;
  /** Interactive controls shown after the finding id at the footer's left. */
  actions?: ReactNode;
  /** Content pinned to the footer's right edge, e.g. the task-run link. */
  footerEnd?: ReactNode;
  /**
   * The inbox report this finding's signal grouped into, when the reverse lookup
   * resolved one. Renders a chip (next to the task-run link) linking to it; absent
   * renders nothing – an unlinked finding shows no report indicator.
   */
  linkedReport?: LinkedSignalReport | null;
  defaultExpanded?: boolean;
  /** True when a shared finding link targets this card – scrolls it into view. */
  highlighted?: boolean;
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const cardRef = useRef<HTMLDivElement>(null);
  // setExpanded too: when a shared link targets a different finding on an
  // already-mounted route, only the search param changes, so the useState
  // initializer's defaultExpanded never re-runs.
  useEffect(() => {
    if (highlighted) {
      setExpanded(true);
      cardRef.current?.scrollIntoView({ block: "center" });
    }
  }, [highlighted]);
  return (
    <Box
      ref={cardRef}
      className={`min-w-0 overflow-hidden rounded-(--radius-2) border bg-gray-1 p-3 ${
        highlighted ? "border-(--accent-8)" : "border-(--gray-6)"
      }`}
    >
      <button
        type="button"
        onClick={() => {
          const next = !expanded;
          setExpanded(next);
          track(ANALYTICS_EVENTS.SCOUT_ACTION, {
            action_type: next ? "expand_emission" : "collapse_emission",
            surface: "scout_detail",
            skill_name: skillName,
            severity: emission.severity,
          });
        }}
        aria-expanded={expanded}
        className="flex w-full select-none items-center gap-2 text-left"
      >
        <CaretRightIcon
          size={11}
          className={`shrink-0 text-gray-9 transition-transform duration-150 ${expanded ? "rotate-90" : ""}`}
        />
        <CompassIcon size={14} className="shrink-0 text-(--iris-9)" />
        <Text className="font-medium text-[13px] text-gray-10">Finding</Text>
        <SeverityBadge severity={emission.severity} />
        <Text className="text-[11px] text-gray-10">
          confidence {Math.round(emission.confidence * 100)}%
        </Text>
        {scoutLabel ? (
          <Flex align="center" gap="1" className="min-w-0">
            <CompassIcon size={11} className="shrink-0 text-gray-9" />
            <Text
              className="truncate text-[11px] text-gray-9"
              title={scoutLabel}
            >
              {scoutLabel}
            </Text>
          </Flex>
        ) : null}
        <span className="flex-1" />
        <RelativeTimestamp timestamp={emission.emitted_at} />
      </button>
      <Box
        className={`mt-2 text-pretty break-words text-[13px] text-gray-11 leading-relaxed [&_code]:text-[11px] [&_p:last-child]:mb-0 [&_p]:mb-1 [&_pre]:text-[11px] ${
          expanded ? "" : "line-clamp-2"
        }`}
      >
        <MarkdownRenderer content={emission.description} />
      </Box>
      {emission.tags?.length ? (
        <Flex gap="1" mt="2" wrap="wrap">
          {emission.tags.map((tag) => (
            <Badge
              key={tag}
              variant="soft"
              color="gray"
              size="1"
              className="text-[11px]"
            >
              {tag}
            </Badge>
          ))}
        </Flex>
      ) : null}
      {expanded ? (
        <Flex
          align="center"
          gap="2"
          mt="2"
          pt="2"
          className="border-t border-t-(--gray-5) text-[11px] text-gray-10"
        >
          <Text className="font-mono text-[11px]">{emission.finding_id}</Text>
          {actions}
          <span className="flex-1" />
          {linkedReport ? (
            <ScoutLinkedReportChip
              report={linkedReport}
              skillName={skillName}
            />
          ) : null}
          {footerEnd}
        </Flex>
      ) : null}
    </Box>
  );
}
