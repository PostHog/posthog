import { Text } from "@components/text";
import {
  describeReportOwner,
  reportWorkState,
  workStateLabel,
} from "@posthog/core/inbox/reportOwnership";
import type { SignalReport } from "@posthog/shared/domain-types";
import { View } from "react-native";

/**
 * Who holds the report and how far the work has got. Renders nothing while the
 * report is unclaimed, so rows keep their current shape.
 */
export function ReportOwnerChip({
  report,
  showState = false,
}: {
  report: SignalReport;
  showState?: boolean;
}) {
  const owner = describeReportOwner(report);
  if (!owner) return null;

  const state = reportWorkState(report);

  return (
    <View className="shrink rounded bg-gray-3 px-1.5 py-0.5">
      <Text className="text-[11px] text-gray-11" numberOfLines={1}>
        {showState ? `${owner.name} · ${workStateLabel(state)}` : owner.name}
      </Text>
    </View>
  );
}
