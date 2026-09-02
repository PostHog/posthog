import { CaretDownIcon, CaretRightIcon } from "@phosphor-icons/react";
import type { GroupSummary } from "@posthog/ui/features/sessions/components/new-thread/buildThreadGroups";
import {
  labelForIconKey,
  motion as motionConfig,
} from "@posthog/ui/features/sessions/components/new-thread/conversationThreadConfig";
import { ToolRow } from "@posthog/ui/features/sessions/components/session-update/ToolRow";
import { DotsCircleSpinner } from "@posthog/ui/primitives/DotsCircleSpinner";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";

interface ToolCallGroupChipProps {
  summary: GroupSummary;
  expanded: boolean;
  turnComplete: boolean;
  onToggle: () => void;
  /** Rendered group items, shown inside the ToolRow's box when expanded. */
  children?: ReactNode;
}

/**
 * A tool-call group is just a ToolRow whose body is the turn's tool work: a
 * collapsible trigger (caret + summary + icon strip) and the same bordered
 * content box. While the turn runs it shows the live action; once complete it
 * shows a verb-led summary.
 */
export function ToolCallGroupChip({
  summary,
  expanded,
  turnComplete,
  onToggle,
  children,
}: ToolCallGroupChipProps) {
  const reduceMotion = useReducedMotion();
  const animate = motionConfig.enabled && !reduceMotion;
  const Caret = expanded ? CaretDownIcon : CaretRightIcon;
  // Spin on THIS group's own in-flight tool, not the turn — a turn split across
  // several chips (by messages/plans) must not keep finished chips spinning.
  const running = !turnComplete && summary.active && summary.liveLabel != null;
  // While running, show both what's happened so far (doneLabel reflects the
  // running tallies) and what's happening now (the live tool title), so a
  // collapsed turn reads as actively-working rather than stalled.
  const hasDone = summary.hasCountableWork;
  const label = running
    ? hasDone
      ? `${summary.doneLabel} · ${summary.liveLabel}`
      : (summary.liveLabel as string)
    : summary.doneLabel;

  return (
    <motion.div
      initial={animate ? motionConfig.chip.initial : false}
      animate={animate ? motionConfig.chip.animate : undefined}
      transition={animate ? motionConfig.chip.transition : undefined}
      className="pl-3"
    >
      <ToolRow
        collapsible
        open={expanded}
        onOpenChange={onToggle}
        content={children}
        leading={
          <span className="shrink-0 pt-1">
            <Caret
              size={12}
              weight="bold"
              className="text-gray-10 transition-colors group-hover:text-gray-12"
            />
          </span>
        }
        trailing={
          !expanded && summary.icons.length > 0 ? (
            <span className="ml-1 flex shrink-0 items-center gap-1.5 text-gray-9">
              {summary.icons.map(({ Icon, key }) => (
                <Tooltip key={key} content={labelForIconKey(key)}>
                  <span className="flex items-center">
                    <Icon size={13} />
                  </span>
                </Tooltip>
              ))}
            </span>
          ) : null
        }
      >
        <span className="flex min-w-0 items-center gap-1.5 font-medium text-[13px] text-gray-11 transition-colors group-hover:text-gray-12">
          {running ? (
            <DotsCircleSpinner size={12} className="shrink-0 text-gray-10" />
          ) : null}
          <span className="truncate">{label}</span>
        </span>
      </ToolRow>
    </motion.div>
  );
}
