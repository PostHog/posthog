import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
import { isDismissedReport } from "@posthog/core/inbox/reportMembership";
import * as Haptics from "expo-haptics";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect } from "react";
import { StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass } from "@/components/Glass";
import { CardButton, ReportDetail } from "@/components/ReportCard";
import {
  useDismissReport,
  useHasLiveImplementationTask,
  useReport,
  useSeenReports,
  useStartReportTask,
} from "@/lib/reports";
import { colors, fonts, radius } from "@/lib/theme";

export default function ReportScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const insets = useSafeAreaInsets();
  const { data: report, isLoading } = useReport(id);
  const dismiss = useDismissReport();
  const startTask = useStartReportTask();
  const liveTask = useHasLiveImplementationTask(id);
  const seenHydrated = useSeenReports((s) => s.hydrated);
  const isSeen = useSeenReports((s) => s.seen.has(id));
  const markSeen = useSeenReports((s) => s.markSeen);

  const reportId = report?.id;
  useEffect(() => {
    if (reportId && seenHydrated && !isSeen) {
      markSeen([reportId]).catch(() => {});
    }
  }, [reportId, seenHydrated, isSeen, markSeen]);

  if (!report) {
    return (
      <View style={styles.root}>
        <Text style={styles.muted}>
          {isLoading ? "Loading" : "This report is not available."}
        </Text>
      </View>
    );
  }

  const canDismiss = !isDismissedReport(report);
  const canStart = canCreateImplementationPr(report, {
    hasLiveImplementationTask: liveTask.data === true,
    // Unknown task state must not offer a second task on live work.
    isTaskLookupPending: liveTask.isPending || liveTask.isError,
  });

  const onDismiss = (): void => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Rigid).catch(() => {});
    dismiss.mutate(report.id, { onSuccess: () => router.back() });
  };

  // Pop back to the drawer and open the task there, so the report does not
  // stay under the chat.
  const onStart = (): void => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(
      () => {},
    );
    startTask.start(report, router.dismissTo).catch(() => {});
  };

  return (
    <View style={styles.root}>
      <ReportDetail report={report} />
      {canDismiss || canStart ? (
        <View style={[styles.actions, { paddingBottom: insets.bottom + 12 }]}>
          {dismiss.isError ? (
            <Text style={styles.error}>Could not dismiss. Try again.</Text>
          ) : null}
          <Glass style={styles.actionsGlass} tint={colors.glassTint}>
            {canDismiss ? (
              <CardButton
                label="Dismiss"
                disabled={dismiss.isPending}
                onPress={onDismiss}
              />
            ) : null}
            {canStart ? (
              <CardButton
                label="Start task"
                primary
                disabled={startTask.isPending}
                onPress={onStart}
              />
            ) : null}
          </Glass>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, paddingHorizontal: 20, paddingTop: 12 },
  muted: { fontFamily: fonts.sans, fontSize: 14, color: colors.inkMute },
  actions: { position: "absolute", left: 16, right: 16, bottom: 0, gap: 8 },
  actionsGlass: {
    flexDirection: "row",
    gap: 8,
    padding: 10,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
  error: {
    alignSelf: "center",
    fontFamily: fonts.sans,
    fontSize: 13,
    color: colors.inkMute,
  },
});
