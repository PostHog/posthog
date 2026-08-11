import { Text } from "@components/text";
import type { SignalReport } from "@posthog/shared/domain-types";
import { memo } from "react";
import { Pressable, View } from "react-native";
import { PrStatusBadge } from "@/features/tasks/components/PrStatusBadge";
import { formatRelativeTime } from "@/lib/format";
import { ActionabilityBadge, PriorityBadge, StatusBadge } from "./ReportBadges";

interface ReportListRowProps {
  report: SignalReport;
  onPress: (report: SignalReport) => void;
}

/**
 * One report in the inbox list.
 *
 * Labels the report with the same `ReportBadges` trio the swipe card and the
 * detail screen use, at the same `sm` size the card uses. The row previously
 * carried a status dot plus a bare colour-coded priority string, which meant a
 * third private copy of "what colour is a P1" and a status the user had to
 * already know the colour code for. Both are gone: the badges say it in words,
 * and there is now exactly one place where a report's labelling can change.
 */
function ReportListRowComponent({ report, onPress }: ReportListRowProps) {
  const timeDisplay = formatRelativeTime(Date.parse(report.updated_at));

  return (
    <Pressable
      onPress={() => onPress(report)}
      className="flex-row items-start gap-2.5 border-gray-6 border-b px-3 py-2.5 active:bg-gray-3"
    >
      <View className="min-w-0 flex-1">
        <Text
          className="font-medium text-[14px] text-gray-12 leading-snug"
          numberOfLines={2}
          ellipsizeMode="tail"
        >
          {report.title ?? "Untitled report"}
        </Text>

        {/* Badges wrap before the timestamp does, so a report with all three
            labels grows the row by one line instead of truncating them. */}
        <View className="mt-1.5 flex-row flex-wrap items-center gap-1.5">
          {report.priority && <PriorityBadge priority={report.priority} />}
          <StatusBadge status={report.status} />
          {report.actionability && (
            <ActionabilityBadge value={report.actionability} />
          )}
          <Text className="text-[11px] text-gray-9" numberOfLines={1}>
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
