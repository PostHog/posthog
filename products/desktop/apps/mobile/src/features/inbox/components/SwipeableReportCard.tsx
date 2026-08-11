import { Text } from "@components/text";
import type { SignalReport } from "@posthog/shared/domain-types";
import * as Haptics from "expo-haptics";
import { GithubLogo, Lightning } from "phosphor-react-native";
import { useMemo, useRef } from "react";
import { Animated, PanResponder, Pressable, View } from "react-native";
import { PrStatusBadge } from "@/features/tasks/components/PrStatusBadge";
import { formatRelativeTime } from "@/lib/format";
import { useThemeColors } from "@/lib/theme";
import { SWIPE_COMMIT_THRESHOLD, stampOpacityRange } from "../swipeIntent";
import { summaryExcerpt } from "../utils";
import { ActionabilityBadge, PriorityBadge, StatusBadge } from "./ReportBadges";

const TAP_THRESHOLD = 10;

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
  const maxDxRef = useRef(0);

  const propsRef = useRef({ report, onDismiss, onAccept, onExpand });
  propsRef.current = { report, onDismiss, onAccept, onExpand };

  const panResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => false,
      onMoveShouldSetPanResponder: (_, gesture) =>
        Math.abs(gesture.dx) > 8 && Math.abs(gesture.dx) > Math.abs(gesture.dy),
      onPanResponderTerminationRequest: () => false,
      onPanResponderGrant: () => {
        maxDxRef.current = 0;
      },
      onPanResponderMove: (_, gesture) => {
        maxDxRef.current = Math.max(maxDxRef.current, Math.abs(gesture.dx));
        translateX.setValue(gesture.dx);
      },
      onPanResponderRelease: (_, gesture) => {
        const p = propsRef.current;

        // Tap detection: no significant movement
        if (maxDxRef.current < TAP_THRESHOLD) {
          translateX.setValue(0);
          p.onExpand(p.report);
          return;
        }

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

  // Non-top cards: static, offset down, no gestures
  if (!isTopCard) {
    return (
      <View
        className="absolute inset-x-0 top-0 rounded-2xl border border-gray-6 bg-card shadow-lg"
        style={{
          bottom: -stackOffset,
          opacity: 0.85,
          elevation: 2,
        }}
      >
        <CardContent
          report={report}
          updatedAt={updatedAt}
          themeColors={themeColors}
          repo={repo}
        />
      </View>
    );
  }

  return (
    <Animated.View
      className="absolute inset-0 rounded-2xl border border-gray-6 bg-card shadow-lg"
      style={{
        transform: [{ translateX }, { rotate }],
        elevation: 4,
      }}
      {...panResponder.panHandlers}
    >
      {/* Intent stamps — corner-mounted and tilted, so the card says what
          letting go will do before it happens. Accept sits on the left, the
          edge that leads a rightward swipe; dismiss mirrors it. */}
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
        className="flex-1 active:opacity-80"
      >
        <CardContent
          report={report}
          updatedAt={updatedAt}
          themeColors={themeColors}
          repo={repo}
        />
      </Pressable>
    </Animated.View>
  );
}

interface CardContentProps {
  report: SignalReport;
  updatedAt: string;
  themeColors: ReturnType<typeof useThemeColors>;
  repo?: string | null;
}

function CardContent({
  report,
  updatedAt,
  themeColors,
  repo,
}: CardContentProps) {
  const excerpt = useMemo(
    () => summaryExcerpt(report.summary),
    [report.summary],
  );

  return (
    <View className="flex-1 p-4">
      {/* Title */}
      <Text
        className="font-bold text-[16px] text-gray-12 leading-snug"
        numberOfLines={2}
      >
        {report.title ?? "Untitled report"}
      </Text>

      {/* Badges row — the three facts that decide the swipe */}
      <View className="mt-2 flex-row flex-wrap items-center gap-1.5">
        {report.priority && <PriorityBadge priority={report.priority} />}
        <StatusBadge status={report.status} />
        {report.actionability && (
          <ActionabilityBadge value={report.actionability} />
        )}
      </View>

      {/* Summary excerpt — plain text, clamped, so every card in the stack is
          the same height and the footer stays put. The full rendered summary
          is a tap away in the expanded view. */}
      <View className="mt-3 flex-1 overflow-hidden">
        {excerpt ? (
          <Text
            className="text-[13px] text-gray-11 leading-[19px]"
            numberOfLines={4}
          >
            {excerpt}
          </Text>
        ) : null}
      </View>

      {/* Footer: signal count + time + repo */}
      <View className="mt-3 flex-row flex-wrap items-center gap-x-3 gap-y-1.5">
        <View className="flex-row items-center gap-1">
          <Lightning size={13} color={themeColors.gray[9]} weight="fill" />
          <Text className="text-[12px] text-gray-9">
            {report.signal_count} signal{report.signal_count !== 1 ? "s" : ""}
          </Text>
        </View>
        <Text className="text-[12px] text-gray-9">·</Text>
        <Text className="text-[12px] text-gray-9">{updatedAt}</Text>
        {repo && (
          <>
            <Text className="text-[12px] text-gray-9">·</Text>
            <View className="min-w-0 flex-row items-center gap-1 rounded-full border border-gray-6 bg-gray-2 px-2 py-0.5">
              <GithubLogo size={10} color={themeColors.gray[9]} weight="fill" />
              <Text className="text-[11px] text-gray-9" numberOfLines={1}>
                {repo}
              </Text>
            </View>
          </>
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
