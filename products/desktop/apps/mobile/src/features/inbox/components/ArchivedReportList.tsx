import { Text } from "@components/text";
import * as Haptics from "expo-haptics";
import { ArrowCounterClockwise, Tray } from "phosphor-react-native";
import { memo, useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  View,
} from "react-native";
import { useThemeColors } from "@/lib/theme";
import { useArchivedReports, useRestoreReport } from "../hooks/useInboxReports";
import type { SignalReport } from "../types";
import {
  dismissalReasonLabel,
  formatReportTimestamp,
  inboxStatusLabel,
  isRestorableReport,
} from "../utils";

interface ArchivedReportListProps {
  onReportPress?: (report: SignalReport) => void;
  contentInsetTop?: number;
}

type Feedback = { kind: "success" | "info" | "error"; text: string };

interface ArchivedRowProps {
  report: SignalReport;
  onPress: (report: SignalReport) => void;
  onRestore: (reportId: string) => void;
  restoring: boolean;
}

const ArchivedRow = memo(function ArchivedRow({
  report,
  onPress,
  onRestore,
  restoring,
}: ArchivedRowProps) {
  const themeColors = useThemeColors();
  const when = formatReportTimestamp(new Date(report.updated_at));
  const restorable = isRestorableReport(report);
  const reasonLabel = report.dismissal_reason
    ? dismissalReasonLabel(report.dismissal_reason)
    : null;

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
          {report.title ?? "Untitled signal"}
        </Text>

        <View className="mt-1 flex-row flex-wrap items-center gap-2">
          {restorable ? (
            <Text className="text-[11px] text-gray-9">Archived {when}</Text>
          ) : (
            <>
              <Text className="rounded bg-status-success/20 px-1.5 py-0.5 font-medium text-[11px] text-status-success">
                {inboxStatusLabel(report.status)}
              </Text>
              <Text className="text-[11px] text-gray-9">{when}</Text>
            </>
          )}
          {reasonLabel ? (
            <Text className="rounded bg-gray-3 px-1.5 py-0.5 text-[11px] text-gray-11">
              {reasonLabel}
            </Text>
          ) : null}
        </View>
      </View>

      {restorable ? (
        <Pressable
          onPress={() => onRestore(report.id)}
          disabled={restoring}
          hitSlop={8}
          accessibilityLabel="Restore report to inbox"
          accessibilityRole="button"
          className="flex-row items-center gap-1.5 self-center rounded-full border border-gray-6 px-3 py-1.5 active:bg-gray-3"
        >
          {restoring ? (
            <ActivityIndicator size="small" color={themeColors.gray[11]} />
          ) : (
            <>
              <ArrowCounterClockwise size={14} color={themeColors.gray[11]} />
              <Text className="font-medium text-[12px] text-gray-11">
                Restore
              </Text>
            </>
          )}
        </Pressable>
      ) : null}
    </Pressable>
  );
});

export function ArchivedReportList({
  onReportPress,
  contentInsetTop = 0,
}: ArchivedReportListProps) {
  const { reports, isLoading, error, refetch } = useArchivedReports();
  const themeColors = useThemeColors();
  const restore = useRestoreReport();
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const feedbackTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showFeedback = useCallback((next: Feedback) => {
    setFeedback(next);
    if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
    feedbackTimer.current = setTimeout(() => setFeedback(null), 4000);
  }, []);

  useEffect(() => {
    return () => {
      if (feedbackTimer.current) clearTimeout(feedbackTimer.current);
    };
  }, []);

  const handlePress = useCallback(
    (report: SignalReport) => onReportPress?.(report),
    [onReportPress],
  );

  const restoreMutate = restore.mutate;
  const handleRestore = useCallback(
    (reportId: string) => {
      restoreMutate(reportId, {
        onSuccess: (restored) => {
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
          showFeedback(
            restored
              ? { kind: "success", text: "Restored to inbox" }
              : { kind: "info", text: "Already back in your inbox" },
          );
        },
        onError: (err) => {
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
          showFeedback({
            kind: "error",
            text: err.message || "Failed to restore report",
          });
        },
      });
    },
    [restoreMutate, showFeedback],
  );

  if (error) {
    return (
      <View className="flex-1 items-center justify-center p-6">
        <Text className="mb-4 text-center text-status-error">{error}</Text>
        <Pressable
          onPress={() => refetch()}
          className="rounded-lg bg-gray-3 px-4 py-2"
        >
          <Text className="text-gray-12">Retry</Text>
        </Pressable>
      </View>
    );
  }

  if (isLoading && reports.length === 0) {
    return (
      <View className="flex-1 items-center justify-center">
        <ActivityIndicator size="large" color={themeColors.accent[9]} />
        <Text className="mt-4 text-gray-11">Loading archive...</Text>
      </View>
    );
  }

  if (reports.length === 0) {
    return (
      <View className="flex-1 items-center justify-center p-6">
        <View className="mb-6 h-16 w-16 items-center justify-center rounded-full bg-gray-3">
          <Tray size={28} color={themeColors.gray[10]} />
        </View>
        <Text className="mb-2 text-center font-semibold text-[16px] text-gray-12">
          Archive is empty
        </Text>
        <Text className="text-center text-[13px] text-gray-11">
          Dismissed and resolved reports show up here.
        </Text>
      </View>
    );
  }

  return (
    <View className="flex-1">
      <FlatList
        data={reports}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => (
          <ArchivedRow
            report={item}
            onPress={handlePress}
            onRestore={handleRestore}
            restoring={restore.isPending && restore.variables === item.id}
          />
        )}
        refreshControl={
          <RefreshControl
            refreshing={isLoading}
            onRefresh={() => refetch()}
            tintColor={themeColors.accent[9]}
            progressViewOffset={contentInsetTop}
          />
        }
        contentContainerStyle={{
          paddingTop: contentInsetTop,
          paddingBottom: 100,
        }}
      />

      {feedback ? (
        <View
          className={`absolute inset-x-4 bottom-24 rounded-xl px-4 py-3 shadow-lg ${
            feedback.kind === "success"
              ? "bg-status-success"
              : feedback.kind === "error"
                ? "bg-status-error"
                : "bg-gray-12"
          }`}
        >
          <Text className="text-center font-medium text-[14px] text-white">
            {feedback.text}
          </Text>
        </View>
      ) : null}
    </View>
  );
}
