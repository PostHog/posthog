import { Text } from "@components/text";
import { inboxStatusLabel } from "@posthog/core/inbox/reportPresentation";
import type {
  SignalReportActionability,
  SignalReportPriority,
  SignalReportStatus,
} from "@posthog/shared/domain-types";
import type { ReactNode } from "react";
import { View } from "react-native";

/**
 * The pill trio that labels a signal report. Lives here rather than beside any
 * one screen because the swipe card, the card's expanded modal, and the report
 * detail screen all label the same report and must not drift apart.
 */

/** `sm` on swipe cards, `md` on the report detail screen. */
export type ReportBadgeSize = "sm" | "md";

interface BadgeColors {
  bg: string;
  text: string;
}

const SIZE_CLASSES: Record<ReportBadgeSize, { box: string; label: string }> = {
  sm: { box: "rounded-full px-2 py-0.5", label: "text-[11px]" },
  md: { box: "rounded px-2 py-1", label: "text-[12px]" },
};

const NEUTRAL: BadgeColors = { bg: "bg-gray-5/20", text: "text-gray-9" };

const statusColorMap: Record<string, BadgeColors> = {
  ready: { bg: "bg-status-success/20", text: "text-status-success" },
  pending_input: { bg: "bg-accent-3", text: "text-accent-11" },
  in_progress: { bg: "bg-status-warning/20", text: "text-status-warning" },
  candidate: { bg: "bg-status-info/20", text: "text-status-info" },
  potential: NEUTRAL,
  failed: { bg: "bg-status-error/20", text: "text-status-error" },
  resolved: { bg: "bg-status-success/20", text: "text-status-success" },
  suppressed: NEUTRAL,
  deleted: NEUTRAL,
};

const priorityColorMap: Record<SignalReportPriority, BadgeColors> = {
  P0: { bg: "bg-status-error/20", text: "text-status-error" },
  P1: { bg: "bg-status-warning/20", text: "text-status-warning" },
  P2: { bg: "bg-status-warning/20", text: "text-status-warning" },
  P3: NEUTRAL,
  P4: NEUTRAL,
};

const actionabilityColorMap: Record<SignalReportActionability, BadgeColors> = {
  immediately_actionable: {
    bg: "bg-status-success/20",
    text: "text-status-success",
  },
  requires_human_input: {
    bg: "bg-status-warning/20",
    text: "text-status-warning",
  },
  not_actionable: NEUTRAL,
};

const actionabilityLabel: Record<SignalReportActionability, string> = {
  immediately_actionable: "Actionable",
  requires_human_input: "Needs input",
  not_actionable: "Not actionable",
};

function Badge({
  colors,
  size,
  children,
}: {
  colors: BadgeColors;
  size: ReportBadgeSize;
  children: ReactNode;
}) {
  const classes = SIZE_CLASSES[size];
  return (
    <View className={`${classes.box} ${colors.bg}`}>
      <Text className={`font-medium ${classes.label} ${colors.text}`}>
        {children}
      </Text>
    </View>
  );
}

export function StatusBadge({
  status,
  size = "sm",
}: {
  status: SignalReportStatus;
  size?: ReportBadgeSize;
}) {
  return (
    <Badge colors={statusColorMap[status] ?? NEUTRAL} size={size}>
      {inboxStatusLabel(status)}
    </Badge>
  );
}

export function PriorityBadge({
  priority,
  size = "sm",
}: {
  priority: SignalReportPriority;
  size?: ReportBadgeSize;
}) {
  return (
    <Badge colors={priorityColorMap[priority] ?? NEUTRAL} size={size}>
      {priority}
    </Badge>
  );
}

export function ActionabilityBadge({
  value,
  size = "sm",
}: {
  value: SignalReportActionability;
  size?: ReportBadgeSize;
}) {
  return (
    <Badge colors={actionabilityColorMap[value] ?? NEUTRAL} size={size}>
      {actionabilityLabel[value] ?? value}
    </Badge>
  );
}
