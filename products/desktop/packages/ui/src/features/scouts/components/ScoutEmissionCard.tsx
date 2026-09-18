import { CaretRightIcon, CompassIcon } from "@phosphor-icons/react";
import type {
  LinkedSignalReport,
  ScoutEmission,
} from "@posthog/api-client/posthog-client";
import { Badge } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { track } from "@posthog/ui/shell/analytics";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { SeverityBadge } from "./ScoutBadges";
import { ScoutLinkedReportChip } from "./ScoutLinkedReportChip";

export function ScoutEmissionCard({
  emission,
  skillName,
  actions,
  footerEnd,
  linkedReport,
  highlighted = false,
}: {
  emission: ScoutEmission;
  /** The emitting scout, attached to analytics events when known. */
  skillName?: string;
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
  /** True when a shared finding link targets this card – scrolls it into view. */
  highlighted?: boolean;
}) {
  const [expanded, setExpanded] = useState(highlighted);
  const cardRef = useRef<HTMLDivElement>(null);
  // A shared link can target a card that is already mounted and collapsed.
  useEffect(() => {
    if (highlighted) {
      setExpanded(true);
      cardRef.current?.scrollIntoView({ block: "center" });
    }
  }, [highlighted]);
  return (
    <div
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
        <SeverityBadge severity={emission.severity} />
        <span className="text-[11px] text-gray-10">
          confidence {Math.round(emission.confidence * 100)}%
        </span>
        <span className="flex-1" />
        <RelativeTimestamp timestamp={emission.emitted_at} />
      </button>
      <div
        className={`mt-2 text-pretty break-words text-[13px] text-gray-11 leading-relaxed [&_code]:text-[11px] [&_p:last-child]:mb-0 [&_p]:mb-1 [&_pre]:text-[11px] ${
          expanded ? "" : "line-clamp-2"
        }`}
      >
        <MarkdownRenderer content={emission.description} />
      </div>
      {emission.tags?.length ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {emission.tags.map((tag) => (
            <Badge key={tag} variant="default" className="text-[11px]">
              {tag}
            </Badge>
          ))}
        </div>
      ) : null}
      {expanded ? (
        <div className="mt-2 flex items-center gap-2 border-t border-t-(--gray-5) pt-2 text-[11px] text-gray-10">
          {actions}
          <span className="flex-1" />
          {linkedReport ? (
            <ScoutLinkedReportChip
              report={linkedReport}
              skillName={skillName}
            />
          ) : null}
          {footerEnd}
        </div>
      ) : null}
    </div>
  );
}
