import { Text } from "@components/text";
import { memo } from "react";
import { Pressable, View } from "react-native";
import { PrStatusBadge } from "@/features/tasks/components/PrStatusBadge";
import { useThemeColors } from "@/lib/theme";
import type { SignalReport } from "../types";
import { formatReportTimestamp } from "../utils";

interface ReportListRowProps {
  report: SignalReport;
  onPress: (report: SignalReport) => void;
}

// Single colored dot conveys status at a glance — full label still
// available on the detail screen.
const statusDotMap: Record<string, string> = {
  ready: "success",
  pending_input: "accent",
  in_progress: "warning",
  candidate: "info",
  potential: "muted",
  failed: "error",
  suppressed: "muted",
  deleted: "muted",
};

const priorityColorMap: Record<string, string> = {
  P0: "text-status-error",
  P1: "text-status-warning",
  P2: "text-status-warning",
  P3: "text-gray-10",
  P4: "text-gray-10",
};

function ReportListRowComponent({ report, onPress }: ReportListRowProps) {
  const themeColors = useThemeColors();
  const timeDisplay = formatReportTimestamp(new Date(report.updated_at));

  const dotKind = statusDotMap[report.status] ?? "muted";
  const dotColor =
    dotKind === "success"
      ? themeColors.status.success
      : dotKind === "warning"
        ? themeColors.status.warning
        : dotKind === "error"
          ? themeColors.status.error
          : dotKind === "info"
            ? themeColors.status.info
            : dotKind === "accent"
              ? themeColors.accent[9]
              : themeColors.gray[8];

  const priorityClass = report.priority
    ? (priorityColorMap[report.priority] ?? "text-gray-10")
    : null;

  return (
    <Pressable
      onPress={() => onPress(report)}
      className="flex-row items-start gap-2.5 border-gray-6 border-b px-3 py-2.5 active:bg-gray-3"
    >
      <View
        className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: dotColor }}
      />

      <View className="min-w-0 flex-1">
        <Text
          className="font-medium text-[14px] text-gray-12 leading-snug"
          numberOfLines={2}
          ellipsizeMode="tail"
        >
          {report.title ?? "Untitled signal"}
        </Text>

        <View className="mt-1 flex-row items-center gap-2">
          {priorityClass ? (
            <Text className={`font-semibold text-[11px] ${priorityClass}`}>
              {report.priority}
            </Text>
          ) : null}
          <Text className="flex-1 text-[11px] text-gray-9" numberOfLines={1}>
            {timeDisplay}
          </Text>
        </View>
      </View>

      {report.implementation_pr_url ? (
        <View className="self-center">
          <PrStatusBadge
            prUrl={report.implementation_pr_url}
            hideWhenUnresolved
            size="sm"
          />
        </View>
      ) : null}
    </Pressable>
  );
}

export const ReportListRow = memo(ReportListRowComponent);
