import { canCreateImplementationPr } from "@posthog/core/inbox/reportActions";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { Alert, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { GlassCircleButton } from "@/components/Glass";
import { ListState } from "@/components/ListState";
import { OptionsSheet } from "@/components/OptionsSheet";
import { ReportDetail } from "@/components/ReportCard";
import { getClient } from "@/lib/client";
import {
  reportKeys,
  useDismissReport,
  useReportDetail,
  useSeenReports,
  useStartReport,
} from "@/lib/reports";
import { colors, fonts } from "@/lib/theme";

export default function ReportScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const queryClient = useQueryClient();
  const detail = useReportDetail(id);
  const report = detail.data;
  const [menu, setMenu] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (error) {
      Alert.alert("Could not update report", error);
      setError(null);
    }
  }, [error]);
  const opened = useRef<string | null>(null);
  const markSeen = useSeenReports((s) => s.markSeen);
  const dismiss = useDismissReport();
  const start = useStartReport();
  const restore = useMutation({
    mutationFn: () =>
      getClient().updateSignalReportState(id, { state: "potential" }),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: reportKeys.all }),
    onError: () => setError("Could not restore report. Try again."),
  });
  const read = useMutation({
    mutationFn: (seen: boolean) => markSeen([id], seen),
    onError: () =>
      setError("Could not save read state on this phone. Try again."),
  });
  useEffect(() => {
    if (!report || opened.current === id) return;
    opened.current = id;
    void markSeen([id]).catch(() =>
      setError("Could not save read state on this phone. Try again."),
    );
  }, [id, report, markSeen]);
  const busy =
    dismiss.isPending || start.isPending || restore.isPending || read.isPending;

  return (
    <View
      style={[
        styles.root,
        { paddingTop: insets.top, paddingBottom: insets.bottom },
      ]}
    >
      <View style={styles.header}>
        <GlassCircleButton
          accessibilityLabel="Back to Self-driving"
          onPress={() =>
            router.canGoBack()
              ? router.back()
              : router.replace("/(drawer)/self-driving")
          }
        >
          <Text style={styles.glyph}>‹</Text>
        </GlassCircleButton>
        <Text style={styles.title}>Report</Text>
        <GlassCircleButton
          accessibilityLabel="Report options"
          onPress={() => setMenu(true)}
        >
          <Text style={styles.glyph}>⋯</Text>
        </GlassCircleButton>
      </View>
      {report ? (
        <ReportDetail report={report} />
      ) : (
        <ListState
          loading={detail.isPending}
          title={detail.isError ? "Could not load report" : "Loading report"}
          description={
            detail.isError ? "Try loading the report again." : undefined
          }
          action={
            detail.isError
              ? { label: "Try again", onPress: () => void detail.refetch() }
              : undefined
          }
        />
      )}
      {menu && report ? (
        <OptionsSheet
          title="Report options"
          onClose={() => setMenu(false)}
          options={[
            {
              label: "Mark unread",
              disabled: busy,
              onPress: () =>
                read.mutate(false, { onSuccess: () => router.back() }),
            },
            {
              label: "Start task",
              disabled: busy || !canCreateImplementationPr(report),
              onPress: () =>
                start.mutate(report, {
                  onSuccess: (task) =>
                    router.replace({
                      pathname: "/(drawer)/task/[id]",
                      params: { id: task.id },
                    }),
                  onError: () => setError("Could not start task. Try again."),
                }),
            },
            {
              label: report.status === "suppressed" ? "Restore" : "Dismiss",
              disabled: busy || report.status === "resolved",
              onPress: () => {
                if (report.status === "suppressed") {
                  restore.mutate();
                  return;
                }
                Alert.alert(
                  "Dismiss report?",
                  report.implementation_pr_url
                    ? "This dismisses the report for the project and closes its open pull request. Restoring the report will not reopen the pull request."
                    : "This dismisses the report for everyone in this project. You can restore it from History.",
                  [
                    { text: "Cancel", style: "cancel" },
                    {
                      text: "Dismiss",
                      style: "destructive",
                      onPress: () =>
                        dismiss.mutate(id, {
                          onSuccess: () => router.back(),
                          onError: () =>
                            setError("Could not dismiss report. Try again."),
                        }),
                    },
                  ],
                );
              },
            },
          ]}
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg, paddingHorizontal: 18 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 8,
  },
  title: {
    flex: 1,
    textAlign: "center",
    fontFamily: fonts.sansSemi,
    fontSize: 18,
    color: colors.ink,
  },
  glyph: { fontSize: 26, color: colors.ink },
  error: { color: colors.danger, padding: 12 },
});
