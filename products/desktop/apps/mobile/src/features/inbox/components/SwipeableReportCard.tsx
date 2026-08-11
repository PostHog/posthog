import { Text } from "@components/text";
import { formatSignalReportSummaryMarkdown } from "@posthog/core/inbox/reportPresentation";
import type { SignalReport } from "@posthog/shared/domain-types";
import * as Haptics from "expo-haptics";
import {
  GithubLogo,
  Lightning,
  MagnifyingGlass,
  UsersThree,
} from "phosphor-react-native";
import { useMemo, useRef } from "react";
import {
  Animated,
  PanResponder,
  Pressable,
  ScrollView,
  View,
} from "react-native";
import { MarkdownText } from "@/features/chat/components/MarkdownText";
import { PrStatusBadge } from "@/features/tasks/components/PrStatusBadge";
import { formatRelativeTime } from "@/lib/format";
import { useThemeColors } from "@/lib/theme";
import { cardReviewerNames, summarizeCardEvidence } from "../cardDetails";
import {
  useInboxReportArtefacts,
  useInboxReportSignals,
} from "../hooks/useInboxReports";
import {
  SWIPE_COMMIT_THRESHOLD,
  shouldClaimHorizontalDrag,
  stampOpacityRange,
} from "../swipeIntent";
import { summaryExcerpt } from "../utils";
import { ActionabilityBadge, PriorityBadge, StatusBadge } from "./ReportBadges";

interface SwipeableReportCardProps {
  report: SignalReport;
  onDismiss: (reportId: string) => void;
  onAccept: (report: SignalReport) => void;
  onExpand: (report: SignalReport) => void;
  isTopCard: boolean;
  /** Vertical offset in px — cards further back sit lower. */
  stackOffset?: number;
  /** Repository slug to show at the bottom of the card. */
  repo?: string | null;
}

export function SwipeableReportCard({
  report,
  onDismiss,
  onAccept,
  onExpand,
  isTopCard,
  stackOffset = 0,
  repo,
}: SwipeableReportCardProps) {
  const themeColors = useThemeColors();
  const translateX = useRef(new Animated.Value(0)).current;

  const propsRef = useRef({ report, onDismiss, onAccept, onExpand });
  propsRef.current = { report, onDismiss, onAccept, onExpand };

  const panResponder = useRef(
    PanResponder.create({
      // Taps must reach the body: the card opens the full report on press and
      // its summary scrolls, so the card only ever claims a moving gesture.
      onStartShouldSetPanResponderCapture: () => false,
      // Capture rather than bubble. The card's body is a scroll view now, and
      // the bubble pass only runs when no descendant wanted the touch — by
      // which point the scroll view owns the gesture and (having scrolled)
      // will refuse to give it back. Asking on the way down gives the card
      // first refusal on every move.
      onMoveShouldSetPanResponderCapture: (_, gesture) =>
        shouldClaimHorizontalDrag(gesture.dx, gesture.dy),
      onPanResponderTerminationRequest: () => false,
      onPanResponderMove: (_, gesture) => {
        translateX.setValue(gesture.dx);
      },
      onPanResponderRelease: (_, gesture) => {
        const p = propsRef.current;

        if (gesture.dx > SWIPE_COMMIT_THRESHOLD) {
          // Swipe right → accept
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
          Animated.timing(translateX, {
            toValue: 500,
            duration: 200,
            useNativeDriver: true,
          }).start(() => {
            p.onAccept(p.report);
          });
        } else if (gesture.dx < -SWIPE_COMMIT_THRESHOLD) {
          // Swipe left → dismiss
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
          Animated.timing(translateX, {
            toValue: -500,
            duration: 200,
            useNativeDriver: true,
          }).start(() => {
            p.onDismiss(p.report.id);
          });
        } else {
          // Spring back
          Animated.spring(translateX, {
            toValue: 0,
            useNativeDriver: true,
            tension: 40,
            friction: 8,
          }).start();
        }
      },
      onPanResponderTerminate: () => {
        Animated.spring(translateX, {
          toValue: 0,
          useNativeDriver: true,
        }).start();
      },
    }),
  ).current;

  const rotate = translateX.interpolate({
    inputRange: [-200, 0, 200],
    outputRange: ["-12deg", "0deg", "12deg"],
    extrapolate: "clamp",
  });

  // Same drag value drives both stamps, so they fade in exactly where
  // `stampOpacity` says they should and hit full opacity at the commit point.
  const acceptOpacity = translateX.interpolate(stampOpacityRange("accept"));
  const dismissOpacity = translateX.interpolate(stampOpacityRange("dismiss"));

  const updatedAt = formatRelativeTime(Date.parse(report.updated_at));

  // Non-top cards: static, offset down, no gestures. They show a few points of
  // edge from behind the top card, so they get the cheap flattened excerpt —
  // rendering markdown and mounting queries for something nobody can read
  // would cost a frame per swipe for nothing.
  if (!isTopCard) {
    return (
      <View
        className="absolute inset-x-0 top-0 overflow-hidden rounded-2xl border border-gray-6 bg-card shadow-lg"
        style={{
          bottom: -stackOffset,
          opacity: 0.85,
          elevation: 2,
        }}
      >
        <CardHeader
          report={report}
          updatedAt={updatedAt}
          themeColors={themeColors}
          repo={repo}
        />
        <CardExcerpt summary={report.summary} />
      </View>
    );
  }

  return (
    <Animated.View
      className="absolute inset-0 overflow-hidden rounded-2xl border border-gray-6 bg-card shadow-lg"
      style={{
        transform: [{ translateX }, { rotate }],
        elevation: 4,
      }}
      {...panResponder.panHandlers}
    >
      {/* Intent stamps — corner-mounted and tilted, so the card says what
          letting go will do before it happens. Accept sits on the left, the
          edge that leads a rightward swipe; dismiss mirrors it.

          Geometry: the deck starts at `inboxHeaderFadeHeight(insets.top)` plus
          the container's 8pt top padding, so a stamp's box top is 20pt (top-5)
          into the card. A ~134x48 box rotated 12° lifts its leading corner by
          (134/2)·sin12° − (48/2)·(1 − cos12°) ≈ 13pt, leaving ~15pt between the
          highest painted pixel and the bottom of the header fade. Lowering
          `top-5` further, or raising the fade, eats that margin. */}
      <Animated.View
        className="absolute top-5 left-4 z-10 rounded-lg border-2 border-status-success bg-status-success/15 px-3 py-1.5"
        style={{ opacity: acceptOpacity, transform: [{ rotate: "-12deg" }] }}
        pointerEvents="none"
      >
        <Text className="font-bold text-[20px] text-status-success uppercase">
          Start task
        </Text>
        <Text className="text-[10px] text-status-success">
          creates a PR if actionable
        </Text>
      </Animated.View>

      <Animated.View
        className="absolute top-5 right-4 z-10 rounded-lg border-2 border-status-error bg-status-error/15 px-3 py-1.5"
        style={{ opacity: dismissOpacity, transform: [{ rotate: "12deg" }] }}
        pointerEvents="none"
      >
        <Text className="font-bold text-[20px] text-status-error uppercase">
          Dismiss
        </Text>
      </Animated.View>

      <Pressable
        onPress={() => onExpand(report)}
        className="flex-1 active:opacity-90"
      >
        {/* Fixed head: what the swipe is about stays put while the body moves,
            so the title can never scroll out from under a half-made decision. */}
        <CardHeader
          report={report}
          updatedAt={updatedAt}
          themeColors={themeColors}
          repo={repo}
        />

        {/* Scrolling body. The card keeps a constant height — it is absolutely
            positioned to fill the deck — so a long report deepens this scroll
            rather than growing the card and breaking the stack. */}
        <ScrollView
          className="flex-1"
          contentContainerStyle={{
            paddingHorizontal: 16,
            paddingBottom: 16,
          }}
          showsVerticalScrollIndicator
          // A drag that reaches the end of the summary must not start bouncing
          // the whole deck's parent instead.
          nestedScrollEnabled
        >
          {report.summary ? (
            <MarkdownText
              content={formatSignalReportSummaryMarkdown(report.summary)}
            />
          ) : (
            <Text className="text-[13px] text-gray-9">
              No summary yet — this report is still being written up.
            </Text>
          )}

          <TopCardDetails reportId={report.id} />
        </ScrollView>
      </Pressable>
    </Animated.View>
  );
}

interface CardHeaderProps {
  report: SignalReport;
  updatedAt: string;
  themeColors: ReturnType<typeof useThemeColors>;
  repo?: string | null;
}

/**
 * Badges, title and meta row, in the same order the report detail screen uses
 * them — a card and the page it opens should not disagree about what matters.
 */
function CardHeader({ report, updatedAt, themeColors, repo }: CardHeaderProps) {
  return (
    <View className="px-4 pt-4 pb-3">
      <View className="flex-row flex-wrap items-center gap-1.5">
        {report.priority && <PriorityBadge priority={report.priority} />}
        <StatusBadge status={report.status} />
        {report.actionability && (
          <ActionabilityBadge value={report.actionability} />
        )}
        {report.is_suggested_reviewer && (
          <View className="rounded-full bg-status-warning/20 px-2 py-0.5">
            <Text className="font-medium text-[11px] text-status-warning">
              For you
            </Text>
          </View>
        )}
      </View>

      <Text
        className="mt-2 font-bold text-[16px] text-gray-12 leading-snug"
        numberOfLines={3}
      >
        {report.title ?? "Untitled report"}
      </Text>

      <View className="mt-2 flex-row flex-wrap items-center gap-x-3 gap-y-1.5">
        <View className="flex-row items-center gap-1">
          <Lightning size={13} color={themeColors.gray[9]} weight="fill" />
          <Text className="text-[12px] text-gray-9">
            {report.signal_count} signal{report.signal_count !== 1 ? "s" : ""}
          </Text>
        </View>
        <Text className="text-[12px] text-gray-9">·</Text>
        <Text className="text-[12px] text-gray-9">{updatedAt}</Text>
        {repo && (
          <View className="min-w-0 flex-row items-center gap-1 rounded-full border border-gray-6 bg-gray-2 px-2 py-0.5">
            <GithubLogo size={10} color={themeColors.gray[9]} weight="fill" />
            <Text className="text-[11px] text-gray-9" numberOfLines={1}>
              {repo}
            </Text>
          </View>
        )}
        {report.implementation_pr_url ? (
          <View className="ml-auto">
            <PrStatusBadge
              prUrl={report.implementation_pr_url}
              hideWhenUnresolved
              size="sm"
            />
          </View>
        ) : null}
      </View>
    </View>
  );
}

/** Flattened, clamped prose — the cheap stand-in for the cards behind. */
function CardExcerpt({ summary }: { summary: string | null | undefined }) {
  const excerpt = useMemo(() => summaryExcerpt(summary), [summary]);
  if (!excerpt) return null;
  return (
    <View className="px-4 pb-4">
      <Text
        className="text-[13px] text-gray-11 leading-[19px]"
        numberOfLines={6}
      >
        {excerpt}
      </Text>
    </View>
  );
}

/**
 * The detail screen's evidence and reviewer strips, for the top card only.
 *
 * Mounted from inside the top card's body rather than passed down, so the
 * queries live and die with the card being decided on — the deck renders three
 * cards, and fanning per-report requests out across all of them would put a
 * burst of requests behind every swipe.
 */
function TopCardDetails({ reportId }: { reportId: string }) {
  const themeColors = useThemeColors();
  const signalsQuery = useInboxReportSignals(reportId);
  // Cache-only: the detail screen and the activity log populate artefacts, and
  // the reviewer strip is a nice-to-have, not worth a poller behind the deck.
  const artefactsQuery = useInboxReportArtefacts(reportId, { enabled: false });

  const signals = signalsQuery.data?.signals;
  const artefacts = artefactsQuery.data?.results;

  const evidence = useMemo(
    () => summarizeCardEvidence(signals, artefacts),
    [signals, artefacts],
  );
  const reviewers = useMemo(() => cardReviewerNames(artefacts), [artefacts]);

  if (!evidence && reviewers.length === 0) return null;

  return (
    <View className="mt-4 gap-2 border-gray-5 border-t pt-3">
      {evidence && (
        <View className="flex-row flex-wrap items-center gap-x-3 gap-y-1">
          <View className="flex-row items-center gap-1.5">
            <MagnifyingGlass size={12} color={themeColors.gray[9]} />
            <Text className="text-[12px] text-gray-10">
              {evidence.findingCount} finding
              {evidence.findingCount !== 1 ? "s" : ""}
            </Text>
          </View>
          {evidence.replayCount > 0 && (
            <>
              <Text className="text-[12px] text-gray-9">·</Text>
              <Text className="text-[12px] text-gray-10">
                {evidence.replayCount} session replay
                {evidence.replayCount !== 1 ? "s" : ""}
              </Text>
            </>
          )}
        </View>
      )}

      {reviewers.length > 0 && (
        <View className="flex-row items-center gap-1.5">
          <UsersThree size={12} color={themeColors.gray[9]} />
          <Text className="flex-1 text-[12px] text-gray-10" numberOfLines={1}>
            {reviewers.join(", ")}
          </Text>
        </View>
      )}
    </View>
  );
}
