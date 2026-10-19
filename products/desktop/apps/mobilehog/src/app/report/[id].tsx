import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
import { isDismissedReport } from "@posthog/core/inbox/reportMembership";
import * as Haptics from "expo-haptics";
import { router, useLocalSearchParams } from "expo-router";
import { useEffect } from "react";
import {
  Alert,
  Linking,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass } from "@/components/Glass";
import { CardButton, ReportDetail } from "@/components/ReportCard";
import {
  hasOpenImplementationPr,
  openPullRequestUrl,
} from "@/lib/reportFilters";
import {
  useDismissReport,
  useHasLiveImplementationTask,
  useMarkReportRead,
  useReport,
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
  const markRead = useMarkReportRead();
  // A report that failed to load or is still loading stays unread.
  const reportId = report?.id;
  useEffect(() => {
    if (reportId) markRead(reportId);
  }, [reportId, markRead]);

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
  const taskCheckFailed = liveTask.isError && canCreateImplementationPr(report);
  // A report with an open PR cannot start another task, so the PR takes that
  // slot.
  const prUrl = canStart ? null : openPullRequestUrl(report);

  const runDismiss = (): void => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Rigid).catch(() => {});
    dismiss.mutate(report.id, { onSuccess: () => router.back() });
  };

  // Dismissing a report also closes its open PR on GitHub.
  const onDismiss = (): void => {
    if (!hasOpenImplementationPr(report)) {
      runDismiss();
      return;
    }
    Alert.alert(
      "Dismiss and close the PR?",
      "The open pull request for this report will be closed.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Dismiss", style: "destructive", onPress: runDismiss },
      ],
    );
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
      {canDismiss || canStart || taskCheckFailed || prUrl ? (
        <View style={[styles.actions, { paddingBottom: insets.bottom + 12 }]}>
          {dismiss.isError ? (
            <Text style={styles.error}>Could not dismiss. Try again.</Text>
          ) : null}
          {taskCheckFailed ? (
            <Pressable
              disabled={liveTask.isFetching}
              onPress={() => liveTask.refetch()}
            >
              <Text style={styles.error}>
                Could not check task status. Tap to try again.
              </Text>
            </Pressable>
          ) : null}
          <Glass style={styles.actionsGlass} tint={colors.glassTint}>
            {canDismiss ? (
              <CardButton
                label="Dismiss"
                disabled={dismiss.isPending}
                onPress={onDismiss}
              />
            ) : null}
            {prUrl ? (
              <CardButton
                label="Open pull request"
                primary
                onPress={() => Linking.openURL(prUrl).catch(() => {})}
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
