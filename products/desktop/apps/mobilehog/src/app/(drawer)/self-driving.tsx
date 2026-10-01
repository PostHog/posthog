import { Host, Picker, Text as SwiftText } from "@expo/ui/swift-ui";
import { pickerStyle, tag } from "@expo/ui/swift-ui/modifiers";
import { formatRelativeAge } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/domain-types";
import * as Haptics from "expo-haptics";
import { useNavigation, useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
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
import { MenuIcon } from "@/components/Icons";
import { PriorityChip } from "@/components/ReportCard";
import { TriageDeck } from "@/components/TriageDeck";
import { REPORT_FILTERS, type ReportFilter } from "@/lib/reportFilters";
import {
  useDismissReport,
  useReports,
  useSeenReports,
  useStartReportTask,
} from "@/lib/reports";
import { colors, fonts, radius } from "@/lib/theme";

const EMPTY: Record<ReportFilter, string> = {
  attention: "All clear",
  "pull-requests": "No pull requests ready",
  dismissed: "Nothing dismissed",
};

export default function SelfDrivingScreen() {
  const navigation = useNavigation<{ openDrawer: () => void }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [filter, setFilter] = useState<ReportFilter>("attention");
  // The deck always works on the reports that need attention.
  const reports = useReports();
  const listed = useReports("", filter);
  const seen = useSeenReports((s) => s.seen);
  const seenHydrated = useSeenReports((s) => s.hydrated);
  const markSeen = useSeenReports((s) => s.markSeen);
  const dismiss = useDismissReport();
  const startTask = useStartReportTask();
  // Locally swiped ids, so a card leaves the deck before the server catches up.
  const [handled, setHandled] = useState<Set<string>>(new Set());
  const [deck, setDeck] = useState<string[] | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), 6000);
    return () => clearTimeout(timer);
  }, [notice]);

  const all = useMemo(
    () => (reports.data ?? []).filter((report) => !handled.has(report.id)),
    [reports.data, handled],
  );
  const rows = filter === "attention" ? all : (listed.data ?? []);
  const unseen = useMemo(
    () => all.filter((report) => !seen.has(report.id)),
    [all, seen],
  );

  // New reports since the last visit open the deck on their own.
  useEffect(() => {
    if (
      deck === null &&
      filter === "attention" &&
      seenHydrated &&
      reports.data &&
      unseen.length > 0
    ) {
      setDeck(unseen.map((report) => report.id));
    }
  }, [deck, filter, seenHydrated, reports.data, unseen]);

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
    if (topId && !seen.has(topId)) markSeen([topId]);
  }, [topId, seen, markSeen]);

  const finish = (report: SignalReport): void => {
    setHandled((current) => new Set(current).add(report.id));
    markSeen([report.id]);
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

  const onStart = (report: SignalReport): void => {
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(
      () => {},
    );
    finish(report);
    startTask.start(report, router.push).catch(() => restore(report));
  };

  const openReport = (report: SignalReport): void => {
    router.push({ pathname: "/report/[id]", params: { id: report.id } });
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
        <Text style={styles.title}>{showDeck ? "Triage" : "Reports"}</Text>
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
            onOpen={openReport}
            starting={startTask.isPending}
            headerHeight={headerHeight}
          />
        </Animated.View>
      ) : (
        <Animated.ScrollView
          key="list"
          entering={FadeIn.duration(240)}
          exiting={FadeOut.duration(160)}
          contentContainerStyle={[
            styles.list,
            { paddingBottom: insets.bottom + 100 },
          ]}
        >
          <Host matchContents={{ vertical: true }}>
            <Picker
              selection={filter}
              onSelectionChange={setFilter}
              modifiers={[pickerStyle("segmented")]}
            >
              {REPORT_FILTERS.map((option) => (
                <SwiftText key={option.value} modifiers={[tag(option.value)]}>
                  {option.label}
                </SwiftText>
              ))}
            </Picker>
          </Host>
          {listed.isLoading ? <Text style={styles.muted}>Loading</Text> : null}
          {rows.length === 0 && !listed.isLoading ? (
            <Text style={styles.sectionTitle}>{EMPTY[filter]}</Text>
          ) : null}
          {rows.map((report) => (
            <Pressable
              key={report.id}
              onPress={() => openReport(report)}
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
              {filter === "attention" && !seen.has(report.id) ? (
                <View style={styles.newDot} />
              ) : null}
            </Pressable>
          ))}
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
      {!showDeck && filter === "attention" && all.length > 0 ? (
        <Animated.View
          entering={FadeInDown.duration(260)}
          exiting={FadeOutDown.duration(180)}
          style={[styles.floating, { paddingBottom: insets.bottom + 14 }]}
        >
          <FadeScrim style={styles.floatingScrim} />
          <Pressable
            onPress={() => setDeck(all.map((report) => report.id))}
            style={({ pressed }) => [
              styles.triage,
              pressed && { opacity: 0.8 },
            ]}
          >
            <Text style={styles.triageText}>
              Triage {all.length} report{all.length === 1 ? "" : "s"}
            </Text>
          </Pressable>
        </Animated.View>
      ) : null}
    </DrawerScene>
  );
}

const styles = StyleSheet.create({
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
  list: { paddingHorizontal: 18, paddingTop: 8, gap: 10 },
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
  muted: { fontFamily: fonts.sans, fontSize: 14, color: colors.inkMute },
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
