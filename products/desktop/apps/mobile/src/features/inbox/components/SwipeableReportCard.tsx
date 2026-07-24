import { Text } from "@components/text";
import { formatDistanceToNow } from "date-fns";
import * as Haptics from "expo-haptics";
import { GithubLogo, Lightning } from "phosphor-react-native";
import { useRef } from "react";
import { Animated, PanResponder, Pressable, View } from "react-native";
import { MarkdownText } from "@/features/chat/components/MarkdownText";
import { PrStatusBadge } from "@/features/tasks/components/PrStatusBadge";
import { useThemeColors } from "@/lib/theme";
import type {
  SignalReport,
  SignalReportPriority,
  SignalReportStatus,
} from "../types";
import { inboxStatusLabel } from "../utils";

const SWIPE_THRESHOLD = 120;
const TAP_THRESHOLD = 10;

const statusColorMap: Record<string, { bg: string; text: string }> = {
  ready: { bg: "bg-status-success/20", text: "text-status-success" },
  pending_input: { bg: "bg-accent-3", text: "text-accent-11" },
  in_progress: { bg: "bg-status-warning/20", text: "text-status-warning" },
  candidate: { bg: "bg-status-info/20", text: "text-status-info" },
  potential: { bg: "bg-gray-5/20", text: "text-gray-9" },
  failed: { bg: "bg-status-error/20", text: "text-status-error" },
  suppressed: { bg: "bg-gray-5/20", text: "text-gray-9" },
  deleted: { bg: "bg-gray-5/20", text: "text-gray-9" },
};

const priorityColorMap: Record<
  SignalReportPriority,
  { bg: string; text: string }
> = {
  P0: { bg: "bg-status-error/20", text: "text-status-error" },
  P1: { bg: "bg-status-warning/20", text: "text-status-warning" },
  P2: { bg: "bg-status-info/20", text: "text-status-info" },
  P3: { bg: "bg-gray-5/20", text: "text-gray-9" },
  P4: { bg: "bg-gray-5/20", text: "text-gray-9" },
};

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

function StatusBadge({ status }: { status: SignalReportStatus }) {
  const colors = statusColorMap[status] ?? statusColorMap.potential;
  return (
    <View className={`rounded-full px-2 py-0.5 ${colors.bg}`}>
      <Text className={`font-medium text-[11px] ${colors.text}`}>
        {inboxStatusLabel(status)}
      </Text>
    </View>
  );
}

function PriorityBadge({ priority }: { priority: SignalReportPriority }) {
  const colors = priorityColorMap[priority] ?? priorityColorMap.P4;
  return (
    <View className={`rounded-full px-2 py-0.5 ${colors.bg}`}>
      <Text className={`font-medium text-[11px] ${colors.text}`}>
        {priority}
      </Text>
    </View>
  );
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

        if (gesture.dx > SWIPE_THRESHOLD) {
          // Swipe right → accept
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
          Animated.timing(translateX, {
            toValue: 500,
            duration: 200,
            useNativeDriver: true,
          }).start(() => {
            p.onAccept(p.report);
          });
        } else if (gesture.dx < -SWIPE_THRESHOLD) {
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

  const acceptOpacity = translateX.interpolate({
    inputRange: [0, 120],
    outputRange: [0, 1],
    extrapolate: "clamp",
  });

  const dismissOpacity = translateX.interpolate({
    inputRange: [-120, 0],
    outputRange: [1, 0],
    extrapolate: "clamp",
  });

  const updatedAt = formatDistanceToNow(new Date(report.updated_at), {
    addSuffix: true,
  });

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
      {/* Accept overlay — LEFT side (visible when tilting right) */}
      <Animated.View
        className="absolute top-0 bottom-0 left-0 z-10 w-16 items-center justify-center rounded-l-2xl bg-status-success/30"
        style={{ opacity: acceptOpacity }}
        pointerEvents="none"
      >
        <Text className="font-bold text-[28px] text-status-success">✓</Text>
      </Animated.View>

      {/* Dismiss overlay — RIGHT side (visible when tilting left) */}
      <Animated.View
        className="absolute top-0 right-0 bottom-0 z-10 w-16 items-center justify-center rounded-r-2xl bg-status-error/30"
        style={{ opacity: dismissOpacity }}
        pointerEvents="none"
      >
        <Text className="font-bold text-[28px] text-status-error">✗</Text>
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
  return (
    <View className="flex-1 p-4">
      {/* Title */}
      <Text
        className="font-bold text-[16px] text-gray-12 leading-snug"
        numberOfLines={2}
      >
        {report.title ?? "Untitled report"}
      </Text>

      {/* Badges row */}
      <View className="mt-2 flex-row flex-wrap items-center gap-1.5">
        <StatusBadge status={report.status} />
        {report.priority && <PriorityBadge priority={report.priority} />}
      </View>

      {/* Summary — fills remaining space so footer sticks to the bottom */}
      <View className="mt-3 flex-1 overflow-hidden">
        {report.summary && <MarkdownText content={report.summary} />}
      </View>

      {/* Footer: signal count + time + repo */}
      <View className="mt-3 flex-row items-center gap-3">
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
            <View className="flex-row items-center gap-1 rounded-full border border-gray-6 bg-gray-2 px-2 py-0.5">
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
