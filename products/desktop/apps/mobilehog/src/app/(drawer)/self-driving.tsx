import { formatRelativeAge } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/domain-types";
import * as Haptics from "expo-haptics";
import { useNavigation } from "expo-router";
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
import {
  useDismissReport,
  useReports,
  useSeenReports,
  useStartReport,
} from "@/lib/reports";
import { colors, fonts, radius } from "@/lib/theme";

export default function SelfDrivingScreen() {
  const navigation = useNavigation<{ openDrawer: () => void }>();
  const insets = useSafeAreaInsets();
  const reports = useReports();
  const seen = useSeenReports((s) => s.seen);
  const seenHydrated = useSeenReports((s) => s.hydrated);
  const markSeen = useSeenReports((s) => s.markSeen);
  const dismiss = useDismissReport();
  const start = useStartReport();
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
  const unseen = useMemo(
    () => all.filter((report) => !seen.has(report.id)),
    [all, seen],
  );

  // New reports since the last visit open the deck on their own.
  useEffect(() => {
    if (deck === null && seenHydrated && reports.data && unseen.length > 0) {
      setDeck(unseen.map((report) => report.id));
    }
  }, [deck, seenHydrated, reports.data, unseen]);

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
    start.mutate(report, {
      onSuccess: () =>
        setNotice(`Started "${(report.title ?? "report").slice(0, 40)}"`),
      onError: (error) => {
        restore(report);
        setNotice(error.message);
      },
    });
  };

  const showDeck = deck !== null && deckReports.length > 0;
  const headerHeight = insets.top + 58;

  return (
    <DrawerScene>
      <View style={[styles.header, { paddingTop: insets.top + 6 }]}>
        {showDeck ? (
          <GlassCircleButton onPress={() => setDeck([])}>
            <Text style={styles.headerChevron}>›</Text>
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
            starting={start.isPending}
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
          {notice ? <Text style={styles.notice}>{notice}</Text> : null}
          <Text style={styles.sectionTitle}>
            {all.length === 0 && !reports.isLoading ? "All clear" : "Reports"}
          </Text>
          {reports.isLoading ? <Text style={styles.muted}>Loading</Text> : null}
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
        </Animated.ScrollView>
      )}
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
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingBottom: 6,
  },
  title: { fontFamily: fonts.sansBold, fontSize: 22, color: colors.ink },
  // A down chevron: triage sits over the list like a sheet.
  headerChevron: {
    fontSize: 30,
    lineHeight: 32,
    color: colors.ink,
    marginTop: -4,
    transform: [{ rotate: "90deg" }],
  },
  list: { paddingHorizontal: 18, paddingTop: 8, gap: 10 },
  notice: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.inkSoft,
    backgroundColor: colors.surface,
    padding: 12,
    borderRadius: 14,
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
