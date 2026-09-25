import { Text } from "@components/text";
import {
  buildReportCheckRows,
  latestCheckExplanations,
  type ReportCheckRowData,
  type ReportCheckTone,
  reportChecksMeta,
  splitReportCheckRows,
} from "@posthog/core/inbox/reportChecks";
import type {
  AnySignalReportArtefact,
  SignalReportCheck,
} from "@posthog/shared/domain-types";
import { ChartLine, Clock, Target } from "phosphor-react-native";
import { useMemo, useState } from "react";
import { ActivityIndicator, Alert, Pressable, View } from "react-native";
import {
  useCancelReportCheck,
  useInboxReportChecks,
} from "@/features/inbox/hooks/useInboxReports";
import { useThemeColors } from "@/lib/theme";

const toneStyles: Record<ReportCheckTone, { bg: string; text: string }> = {
  neutral: { bg: "bg-gray-5/20", text: "text-gray-9" },
  info: { bg: "bg-status-info/20", text: "text-status-info" },
  success: { bg: "bg-status-success/20", text: "text-status-success" },
  danger: { bg: "bg-status-error/20", text: "text-status-error" },
  warning: { bg: "bg-status-warning/20", text: "text-status-warning" },
};

function CheckRow({
  row,
  stopping,
  onStop,
}: {
  row: ReportCheckRowData;
  stopping: boolean;
  onStop: (check: SignalReportCheck) => void;
}) {
  const themeColors = useThemeColors();
  const { check, tag, detail, cancelled, cancellable } = row;
  const tone = toneStyles[tag.tone];
  const Icon = check.kind === "agent" ? Clock : ChartLine;

  return (
    <View
      className="rounded-xl border border-gray-6 bg-gray-1 p-3"
      style={{ opacity: cancelled ? 0.6 : 1 }}
    >
      <View className="flex-row items-start gap-2">
        <Icon size={14} color={themeColors.gray[9]} />
        <Text
          className={`flex-1 font-medium text-[13px] text-gray-12 ${
            cancelled ? "line-through" : ""
          }`}
        >
          {check.title}
        </Text>
        <View className={`rounded px-2 py-1 ${tone.bg}`}>
          <Text className={`font-medium text-[11px] ${tone.text}`}>
            {tag.label}
          </Text>
        </View>
      </View>
      {detail ? (
        <Text className="mt-1.5 text-[12px] text-gray-10">{detail}</Text>
      ) : null}
      {cancellable ? (
        <Pressable
          onPress={() => onStop(check)}
          disabled={stopping}
          accessibilityRole="button"
          accessibilityLabel={`Stop check: ${check.title}`}
          accessibilityState={{ disabled: stopping }}
          className="mt-2 flex-row items-center gap-2 self-start rounded-lg border border-gray-6 px-3 py-1.5 active:opacity-60"
        >
          {stopping ? (
            <ActivityIndicator size="small" color={themeColors.gray[11]} />
          ) : null}
          <Text className="font-medium text-[12px] text-gray-11">
            {stopping ? "Stopping" : "Stop"}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}

/**
 * What is still watching this report, and what the checks that already ran decided. Until a
 * check produces a verdict nothing else on the screen mentions it, so a reader cannot otherwise
 * tell that one is scheduled, waiting for the report to resolve, or expired without ever running.
 *
 * Renders nothing when the report carries no checks.
 */
export function ReportChecks({
  reportId,
  artefacts,
}: {
  reportId: string;
  artefacts: AnySignalReportArtefact[];
}) {
  const themeColors = useThemeColors();
  const { data } = useInboxReportChecks(reportId);
  const cancelCheck = useCancelReportCheck(reportId);
  const [showRetired, setShowRetired] = useState(false);

  const checks = data?.results ?? [];
  const rows = useMemo(
    () => buildReportCheckRows(checks, latestCheckExplanations(artefacts)),
    [checks, artefacts],
  );

  if (checks.length === 0) return null;

  const { visible, hidden } = splitReportCheckRows(rows);

  const confirmStop = (check: SignalReportCheck) => {
    Alert.alert(
      "Stop this check?",
      `"${check.title}" will not run, and nothing will report back on it. Results it already recorded stay on this report.`,
      [
        { text: "Keep it", style: "cancel" },
        {
          text: "Stop check",
          style: "destructive",
          onPress: () => {
            cancelCheck.mutate(check.id, {
              onError: (error) =>
                Alert.alert(
                  "Couldn’t stop this check",
                  error instanceof Error ? error.message : "Try again shortly.",
                ),
            });
          },
        },
      ],
    );
  };

  return (
    <View className="mb-4">
      <View className="mb-2 flex-row items-center gap-1.5">
        <Target size={14} color={themeColors.gray[12]} />
        <Text className="font-semibold text-[14px] text-gray-12">
          Follow-up checks
        </Text>
        <Text className="text-[12px] text-gray-9">
          {reportChecksMeta(checks)}
        </Text>
      </View>
      <View className="gap-2">
        {(showRetired ? rows : visible).map((row) => (
          <CheckRow
            key={row.check.id}
            row={row}
            stopping={
              cancelCheck.isPending && cancelCheck.variables === row.check.id
            }
            onStop={confirmStop}
          />
        ))}
      </View>
      {hidden.length > 0 && !showRetired ? (
        <Pressable
          onPress={() => setShowRetired(true)}
          accessibilityRole="button"
          className="mt-2 self-start py-1 active:opacity-60"
        >
          <Text className="font-medium text-[12px] text-gray-11">
            Show {hidden.length} more
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}
