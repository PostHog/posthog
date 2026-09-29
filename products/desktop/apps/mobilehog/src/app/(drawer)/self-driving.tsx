import { buildCreatePrReportPrompt } from "@posthog/core/inbox/reportActions";
import { formatRelativeAge } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/domain-types";
import * as Haptics from "expo-haptics";
import { useNavigation, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import {
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
import { FadeScrim } from "@/components/FadeScrim";
import { GlassCircleButton } from "@/components/Glass";
import { MenuIcon, SteeringIcon } from "@/components/Icons";
import { ListState } from "@/components/ListState";
import { PriorityChip } from "@/components/ReportCard";
import { TriageDeck } from "@/components/TriageDeck";
import {
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
  const reports = useReports();
  const seen = useSeenReports((s) => s.seen);
  const markSeen = useSeenReports((s) => s.markSeen);
  const dismiss = useDismissReport();
  const start = useStartReport();
  // Locally swiped ids, so a card leaves the deck before the server catches up.
  const [handled, setHandled] = useState<Set<string>>(new Set());
  const [deck, setDeck] = useState<string[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [markingRead, setMarkingRead] = useState(false);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  const all = useMemo(
    () => (reports.data ?? []).filter((report) => !handled.has(report.id)),
    [reports.data, handled],
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

  const onDismiss = (report: SignalReport): void => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Rigid).catch(() => {});
    finish(report);
    dismiss.mutate(report.id, {
      onError: (error) => {
        restore(report);
        setNotice(error.message);
      },
    });
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
      await markSeen(unseen.map((report) => report.id));
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
          <GlassCircleButton onPress={() => setDeck([])}>
            <Text style={styles.headerGlyph}>×</Text>
          </GlassCircleButton>
        ) : (
          <GlassCircleButton onPress={() => navigation.openDrawer()}>
            <MenuIcon />
          </GlassCircleButton>
        )}
        <Text style={styles.title}>{showDeck ? "Report" : "Inbox"}</Text>
        <View style={{ width: 46 }} />
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
            { paddingBottom: insets.bottom + (all.length > 0 ? 100 : 24) },
          ]}
        >
          {all.length > 0 ? (
            <Text style={styles.sectionTitle}>For you</Text>
          ) : null}
          {unseen.length > 0 ? (
            <Pressable
              accessibilityRole="button"
              disabled={markingRead}
              onPress={() => void markLoadedRead()}
              style={styles.readAction}
            >
              <Text style={styles.actionText}>
                {markingRead ? "Saving" : "Mark as read"}
              </Text>
            </Pressable>
          ) : null}
          {reports.isError ? (
            <ListState
              title="Could not load your inbox"
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
                  ? "Loading your inbox"
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
              onPress={() => setDeck([report.id])}
              style={({ pressed }) => [styles.row, pressed && { opacity: 0.5 }]}
            >
              {report.priority ? (
                <PriorityChip priority={report.priority} />
              ) : null}
              <View style={styles.rowBody}>
                <Text style={styles.rowTitle} numberOfLines={2}>
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
      {notice ? (
        <Animated.View
          key={notice}
          entering={FadeInDown.duration(220)}
          exiting={FadeOutDown.duration(180)}
          style={[styles.toast, { bottom: insets.bottom + 124 }]}
          pointerEvents="none"
        >
          <Text style={styles.notice}>{notice}</Text>
        </Animated.View>
      ) : null}
      {!showDeck && all.length > 0 ? (
        <Animated.View
          entering={FadeInDown.duration(260)}
          exiting={FadeOutDown.duration(180)}
          style={[styles.floating, { paddingBottom: insets.bottom + 14 }]}
        >
          <FadeScrim style={styles.floatingScrim} />
          <Pressable
            onPress={() =>
              setDeck((unseen.length > 0 ? unseen : all).map((r) => r.id))
            }
            style={({ pressed }) => [
              styles.triage,
              pressed && { opacity: 0.8 },
            ]}
          >
            <Text style={styles.triageText}>
              {unseen.length > 0
                ? `Triage ${unseen.length} new report${unseen.length === 1 ? "" : "s"}`
                : `Triage ${all.length} report${all.length === 1 ? "" : "s"}`}
            </Text>
          </Pressable>
        </Animated.View>
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
  list: { flexGrow: 1, paddingHorizontal: 18, paddingTop: 8, gap: 10 },
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
  floating: {
    position: "absolute",
    left: 18,
    right: 18,
    bottom: 0,
  },
  floatingScrim: {
    position: "absolute",
    left: -18,
    right: -18,
    top: -48,
    bottom: 0,
  },
  triage: {
    backgroundColor: colors.dark,
    borderRadius: radius.pill,
    paddingVertical: 16,
    alignItems: "center",
    shadowColor: "#000",
    shadowOpacity: 0.18,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
  },
  triageText: {
    fontFamily: fonts.sansSemi,
    fontSize: 16,
    color: colors.darkText,
  },
  sectionTitle: {
    fontFamily: fonts.sansSemi,
    fontSize: 12,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.inkMute,
    marginTop: 8,
    marginLeft: 4,
  },
  row: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
    backgroundColor: colors.surface,
    borderRadius: 18,
    padding: 14,
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
