import { buildCreatePrReportPrompt } from "@posthog/core/inbox/reportActions";
import { formatRelativeAge } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/domain-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as Haptics from "expo-haptics";
import { useLocalSearchParams, useNavigation, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from "react-native";
import Animated, {
  FadeIn,
  FadeInDown,
  FadeOut,
  FadeOutDown,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { DrawerScene } from "@/components/DrawerScene";
import { GlassCircleButton } from "@/components/Glass";
import { MenuIcon, SteeringIcon } from "@/components/Icons";
import { ListState } from "@/components/ListState";
import { OptionsSheet } from "@/components/OptionsSheet";
import { PriorityChip } from "@/components/ReportCard";
import { TriageDeck } from "@/components/TriageDeck";
import { getClient } from "@/lib/client";
import { type ReportSort, usePrefs } from "@/lib/prefs";
import {
  REPORT_SORTS,
  type ReportView,
  useDismissReport,
  useReports,
  useSeenReports,
  useStartReport,
} from "@/lib/reports";
import { useSessions } from "@/lib/session";
import { colors, fonts, radius } from "@/lib/theme";

export default function SelfDrivingScreen() {
  const navigation = useNavigation<{ openDrawer: () => void }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [view, setView] = useState<ReportView>("active");
  const reports = useReports(view);
  const { reportId } = useLocalSearchParams<{ reportId?: string }>();
  const queryClient = useQueryClient();
  const [undoReport, setUndoReport] = useState<SignalReport | null>(null);
  const reopen = useMutation({
    mutationFn: (id: string) =>
      getClient().updateSignalReportState(id, { state: "potential" }),
    onSuccess: () => {
      setUndoReport(null);
      setHandled(new Set());
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
      setNotice("Report restored.");
    },
    onError: () => setNotice("Could not restore report. Try again."),
  });
  const sort = usePrefs((s) => s.reportSort);
  const savePrefs = usePrefs((s) => s.set);
  const [menu, setMenu] = useState<"sort" | "actions" | null>(null);
  const syncError = useSeenReports((s) => s.syncError);
  const [syncNoticeDismissed, setSyncNoticeDismissed] = useState(false);
  useEffect(() => {
    if (!syncError) setSyncNoticeDismissed(false);
  }, [syncError]);
  const seen = useSeenReports((s) => s.seen);
  const markSeen = useSeenReports((s) => s.markSeen);
  const dismiss = useDismissReport();
  const start = useStartReport();
  // Locally swiped ids, so a card leaves the deck before the server catches up.
  const [handled, setHandled] = useState<Set<string>>(new Set());
  const [deck, setDeck] = useState<string[] | null>(null);
  useEffect(() => {
    if (reportId)
      router.replace({ pathname: "/report", params: { id: reportId } });
  }, [reportId, router]);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [markingRead, setMarkingRead] = useState(false);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  const all = useMemo(
    () =>
      (reports.data ?? []).filter(
        (report) =>
          !handled.has(report.id) &&
          (view !== "unread" || !seen.has(report.id)),
      ),
    [reports.data, handled, view, seen],
  );
  const unseen = useMemo(
    () => all.filter((report) => !seen.has(report.id)),
    [all, seen],
  );

  const deckReports = useMemo(
    () =>
      (deck ?? [])
        .map((id) => all.find((report) => report.id === id))
        .filter((report): report is SignalReport => !!report),
    [deck, all],
  );
  // Whatever surfaces at the top of the deck counts as seen.
  const topId = deckReports[0]?.id;
  useEffect(() => {
    if (topId && !seen.has(topId))
      markSeen([topId]).catch(() =>
        setNotice("Could not mark the report as read."),
      );
  }, [topId, seen, markSeen]);

  const finish = (report: SignalReport): void => {
    setHandled((current) => new Set(current).add(report.id));
    markSeen([report.id]).catch(() =>
      setNotice("Could not mark the report as read."),
    );
  };

  // A failed action leaves the report open on the server, so put the card back
  // in the deck for another try.
  const restore = (report: SignalReport): void => {
    setHandled((current) => {
      const next = new Set(current);
      next.delete(report.id);
      return next;
    });
  };

  const dismissNow = (report: SignalReport): void => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Rigid).catch(() => {});
    finish(report);
    dismiss.mutate(report.id, {
      onSuccess: () => {
        setUndoReport(report);
        setNotice("Report dismissed for this project.");
      },
      onError: (error) => {
        restore(report);
        setNotice(error.message);
      },
    });
  };

  const onDismiss = (report: SignalReport): void => {
    if (dismiss.isPending) return;
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
          onPress: () => dismissNow(report),
        },
      ],
    );
  };

  // Open the chat immediately with the report prompt in it (the same pending
  // pattern as the new-chat screen), then re-key it to the real task id.
  const onStart = (report: SignalReport): void => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(
      () => {},
    );
    finish(report);
    const tempId = `new-${Date.now()}`;
    const prompt = buildCreatePrReportPrompt({ reportId: report.id });
    const { startPending, adopt, failPending } = useSessions.getState();
    startPending(tempId, prompt, `local-${Date.now()}`);
    router.push({ pathname: "/(drawer)/task/[id]", params: { id: tempId } });
    start.mutate(report, {
      onSuccess: (task) => {
        adopt(tempId, task);
        router.replace({
          pathname: "/(drawer)/task/[id]",
          params: { id: task.id },
        });
      },
      onError: (error) => {
        restore(report);
        failPending(tempId, error.message);
      },
    });
  };

  const refresh = async (): Promise<void> => {
    if (reports.isFetching || refreshing) return;
    setRefreshing(true);
    try {
      await reports.refetch();
    } finally {
      setRefreshing(false);
    }
  };

  const markLoadedRead = async (): Promise<void> => {
    if (markingRead) return;
    setMarkingRead(true);
    try {
      const ids = unseen.map((report) => report.id);
      await markSeen(ids);
      if (view === "unread") void reports.refetch();
      setNotice(
        `${ids.length} report${ids.length === 1 ? "" : "s"} marked as read.`,
      );
    } catch {
      setNotice("Could not mark reports as read.");
    } finally {
      setMarkingRead(false);
    }
  };

  const showDeck = deck !== null && deckReports.length > 0;
  const headerHeight = insets.top + 58;

  return (
    <DrawerScene>
      <View style={[styles.header, { paddingTop: insets.top + 6 }]}>
        {showDeck ? (
          <GlassCircleButton
            accessibilityLabel="Close triage"
            onPress={() => {
              setDeck([]);
              if (view === "unread") void reports.refetch();
            }}
          >
            <Text style={styles.headerGlyph}>×</Text>
          </GlassCircleButton>
        ) : (
          <GlassCircleButton
            accessibilityLabel="Open menu"
            onPress={() => navigation.openDrawer()}
          >
            <MenuIcon />
          </GlassCircleButton>
        )}
        <Text style={styles.title}>{showDeck ? "Triage" : "Self-driving"}</Text>
        {!showDeck ? (
          <GlassCircleButton
            accessibilityLabel="Report options"
            onPress={() => setMenu("actions")}
          >
            <Text style={styles.headerGlyph}>⋯</Text>
          </GlassCircleButton>
        ) : (
          <View style={{ width: 46 }} />
        )}
      </View>

      {showDeck ? (
        <Animated.View
          key="deck"
          exiting={FadeOutDown.duration(200)}
          style={StyleSheet.absoluteFill}
          pointerEvents="box-none"
        >
          <TriageDeck
            reports={deckReports}
            onDismiss={onDismiss}
            onStart={onStart}
            starting={start.isPending}
            headerHeight={headerHeight}
          />
        </Animated.View>
      ) : (
        <Animated.ScrollView
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => void refresh()}
            />
          }
          key="list"
          entering={FadeIn.duration(240)}
          exiting={FadeOut.duration(160)}
          contentContainerStyle={[
            styles.list,
            { paddingBottom: insets.bottom + 24 },
          ]}
        >
          <Text style={styles.rowMeta}>
            {view === "history"
              ? "History"
              : view === "unread"
                ? "Unread reports"
                : "Reports for you"}
          </Text>
          {all.length > 0 ? (
            <View style={styles.toolbar}>
              <Text style={styles.rowMeta}>
                {unseen.length ? `${unseen.length} unread` : "All read"}
              </Text>
              <Pressable
                accessibilityRole="button"
                accessibilityLabel="Sort reports"
                onPress={() => setMenu("sort")}
                style={styles.sortButton}
              >
                <Text style={styles.actionText}>
                  {(REPORT_SORTS[sort] ?? REPORT_SORTS.newest).label} ↓
                </Text>
              </Pressable>
            </View>
          ) : null}
          {reports.isError ? (
            <ListState
              title="Could not load reports"
              description="Check your connection and try again."
              icon={<SteeringIcon />}
              action={{
                label: "Retry",
                onPress: () => void reports.refetch(),
                disabled: reports.isFetching,
              }}
            />
          ) : all.length === 0 ? (
            <ListState
              loading={reports.isLoading}
              icon={<SteeringIcon />}
              title={
                reports.isLoading
                  ? "Loading reports"
                  : reports.hasNextPage
                    ? "No reports in this page"
                    : "No reports to review"
              }
              description={
                reports.isLoading
                  ? undefined
                  : reports.hasNextPage
                    ? "Load more to check the remaining reports."
                    : "Reports that need your review will appear here."
              }
            />
          ) : null}
          {all.map((report) => (
            <Pressable
              key={report.id}
              accessibilityRole="button"
              onPress={() => {
                router.push({ pathname: "/report", params: { id: report.id } });
              }}
              accessibilityLabel={`${seen.has(report.id) ? "" : "Unread. "}${report.title ?? "Untitled report"}`}
              style={({ pressed }) => [
                styles.row,
                !seen.has(report.id) && styles.rowUnread,
                pressed && { opacity: 0.5 },
              ]}
            >
              {report.priority ? (
                <PriorityChip priority={report.priority} />
              ) : null}
              <View style={styles.rowBody}>
                <Text
                  style={[
                    styles.rowTitle,
                    !seen.has(report.id) && styles.rowTitleUnread,
                  ]}
                  numberOfLines={3}
                >
                  {report.title ?? "Untitled report"}
                </Text>
                <Text style={styles.rowMeta}>
                  {report.signal_count} signal
                  {report.signal_count === 1 ? "" : "s"} ·{" "}
                  {formatRelativeAge(report.updated_at)}
                </Text>
              </View>
              {!seen.has(report.id) ? <View style={styles.newDot} /> : null}
            </Pressable>
          ))}
          {reports.hasNextPage ? (
            <Pressable
              disabled={reports.isFetchingNextPage}
              onPress={() => void reports.fetchNextPage()}
              style={styles.readAction}
            >
              <Text style={styles.actionText}>
                {reports.isFetchingNextPage ? "Loading" : "Load more"}
              </Text>
            </Pressable>
          ) : null}
        </Animated.ScrollView>
      )}
      {syncError && !syncNoticeDismissed ? (
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            padding: 12,
            gap: 8,
          }}
        >
          <Text style={{ color: colors.inkSoft, flex: 1, fontSize: 13 }}>
            Read changes stay on this phone until sync is available.
          </Text>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Dismiss sync notice"
            onPress={() => setSyncNoticeDismissed(true)}
            style={{ padding: 12 }}
          >
            <Text style={{ color: colors.inkSoft }}>×</Text>
          </Pressable>
        </View>
      ) : null}
      {notice ? (
        <Animated.View
          key={notice}
          entering={FadeInDown.duration(220)}
          exiting={FadeOutDown.duration(180)}
          style={[styles.toast, { bottom: insets.bottom + 20 }]}
          pointerEvents="auto"
        >
          <Text accessibilityRole="alert" style={styles.notice}>
            {notice}
          </Text>
          {undoReport ? (
            <Pressable
              accessibilityRole="button"
              disabled={reopen.isPending}
              onPress={() => reopen.mutate(undoReport.id)}
              style={styles.sortButton}
            >
              <Text style={styles.actionText}>
                {reopen.isPending ? "Restoring" : "Undo dismissal"}
              </Text>
            </Pressable>
          ) : null}
        </Animated.View>
      ) : null}
      {menu ? (
        <OptionsSheet
          title={menu === "sort" ? "Sort reports" : "Self-driving"}
          onClose={() => setMenu(null)}
          options={
            menu === "sort"
              ? Object.entries(REPORT_SORTS).map(([value, option]) => ({
                  label: option.label,
                  selected: sort === value,
                  onPress: () => {
                    void savePrefs({ reportSort: value as ReportSort }).catch(
                      () => setNotice("Could not save sort order."),
                    );
                  },
                }))
              : [
                  ...Object.entries({
                    active: "Reports for you",
                    unread: "Unread",
                    history: "History",
                  }).map(([value, label]) => ({
                    label,
                    selected: view === value,
                    onPress: () => {
                      setView(value as ReportView);
                      setHandled(new Set());
                    },
                  })),
                  {
                    label: "Triage reports",
                    disabled: view === "history" || all.length === 0,
                    onPress: () =>
                      setDeck(
                        (unseen.length > 0 ? unseen : all).map(
                          (report) => report.id,
                        ),
                      ),
                  },
                  ...(unseen.length > 0
                    ? [
                        {
                          label: markingRead
                            ? "Marking reports as read"
                            : `Mark ${unseen.length} report${unseen.length === 1 ? "" : "s"} as read`,
                          disabled: markingRead,
                          onPress: () =>
                            Alert.alert(
                              "Mark reports as read?",
                              `This marks ${unseen.length} loaded report${unseen.length === 1 ? "" : "s"} as read on your devices. Reports stay in the list.`,
                              [
                                { text: "Cancel", style: "cancel" },
                                {
                                  text: "Mark as read",
                                  onPress: () => void markLoadedRead(),
                                },
                              ],
                            ),
                        },
                      ]
                    : []),
                ]
          }
        />
      ) : null}
    </DrawerScene>
  );
}

const styles = StyleSheet.create({
  readAction: { paddingVertical: 12 },
  actionText: {
    fontFamily: fonts.sansMedium,
    color: colors.accent,
    fontSize: 14,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingBottom: 6,
  },
  title: { fontFamily: fonts.sansBold, fontSize: 22, color: colors.ink },
  headerGlyph: {
    fontSize: 26,
    lineHeight: 28,
    color: colors.ink,
    marginTop: -2,
  },
  list: { flexGrow: 1, paddingHorizontal: 12, paddingTop: 8, gap: 2 },
  toast: { position: "absolute", left: 18, right: 18, alignItems: "center" },
  notice: {
    fontFamily: fonts.sansMedium,
    fontSize: 14,
    color: colors.darkText,
    backgroundColor: colors.dark,
    paddingHorizontal: 16,
    paddingVertical: 11,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
  toolbar: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  sortButton: { minHeight: 44, justifyContent: "center" },
  rowUnread: { backgroundColor: colors.surface },
  rowTitleUnread: { fontFamily: fonts.sansSemi, color: colors.ink },
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
    borderRadius: 12,
    paddingVertical: 16,
    paddingHorizontal: 12,
  },
  rowBody: { flex: 1, gap: 3 },
  rowTitle: {
    fontFamily: fonts.sansMedium,
    fontSize: 15,
    lineHeight: 20,
    color: colors.ink,
  },
  rowMeta: { fontFamily: fonts.sans, fontSize: 12, color: colors.inkMute },
  newDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.accent,
    marginTop: 6,
  },
});
