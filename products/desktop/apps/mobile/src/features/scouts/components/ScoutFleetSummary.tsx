import { Text } from "@components/text";
import type { FleetSummary } from "@posthog/core/scouts/scoutPresentation";
import { View } from "react-native";
import { formatRate } from "../lib/scoutRows";

interface ScoutFleetSummaryProps {
  summary: FleetSummary;
  /** What the run-derived numbers cover, e.g. "last 3 days". */
  windowLabel: string;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View className="flex-1 rounded-lg border border-gray-5 bg-card px-3 py-2.5">
      <Text className="font-semibold text-[18px] text-gray-12">{value}</Text>
      <Text className="mt-0.5 text-[11px] text-gray-10">{label}</Text>
    </View>
  );
}

/**
 * Fleet header: how much of the fleet is on, what it is doing right now, and
 * how its recent runs went. Success and emit rates describe only the visible
 * run window, so the window is named underneath rather than left implied.
 */
export function ScoutFleetSummary({
  summary,
  windowLabel,
}: ScoutFleetSummaryProps) {
  return (
    <View className="gap-2 px-4 pb-3">
      <View className="flex-row gap-2">
        <Stat
          label="Enabled"
          value={`${summary.enabledCount}/${summary.totalCount}`}
        />
        <Stat label="Running" value={String(summary.runningCount)} />
      </View>
      <View className="flex-row gap-2">
        <Stat label="Success rate" value={formatRate(summary.successRate)} />
        <Stat label="Emit rate" value={formatRate(summary.emitRate)} />
      </View>

      <View className="flex-row flex-wrap items-center gap-x-2">
        <Text className="text-[12px] text-gray-10">
          {summary.emittedCount} signal{summary.emittedCount === 1 ? "" : "s"}{" "}
          emitted · {windowLabel}
        </Text>
        {/* Auto-paused scouts sort below the enabled ones, so the count has to
            lead here — switching them back on is the only way to recover them. */}
        {summary.systemPausedCount > 0 ? (
          <Text className="text-[12px] text-status-error">
            {summary.systemPausedCount} auto-paused
          </Text>
        ) : null}
        {summary.pausingSoonCount > 0 ? (
          <Text className="text-[12px] text-status-warning">
            {summary.pausingSoonCount} pausing soon
          </Text>
        ) : null}
      </View>
    </View>
  );
}
