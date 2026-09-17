import type { SignalReport } from "@posthog/shared/domain-types";
import * as Haptics from "expo-haptics";
import { useState } from "react";
import {
  Image,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, {
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass, GlassCircleButton } from "@/components/Glass";
import {
  CardButton,
  ReportDetail,
  ReportSummary,
} from "@/components/ReportCard";
import { colors, fonts, radius } from "@/lib/theme";

const SWIPE_THRESHOLD = 110;
const FLY_OUT = 600;
const CARD_RADIUS = 28;
// Room below the top card for the stack to peek out.
const STACK_PEEK = 28;

interface TriageDeckProps {
  reports: SignalReport[];
  onDismiss: (report: SignalReport) => void;
  onStart: (report: SignalReport) => void;
  starting?: boolean;
  // Height of the screen header the deck sits under; the frame starts below it.
  headerHeight: number;
}

// Tinder-style stack: swipe left to dismiss, right to start a task, or open
// the card in place to read the whole report before deciding.
export function TriageDeck({
  reports,
  onDismiss,
  onStart,
  starting,
  headerHeight,
}: TriageDeckProps) {
  const { width, height } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const [expanded, setExpanded] = useState(false);
  const [frame, setFrame] = useState({ x: 0, y: 0, w: 0, h: 0 });
  const x = useSharedValue(0);
  const y = useSharedValue(0);
  const grow = useSharedValue(0);
  const top = reports[0];
  const rest = reports.slice(1, 3);

  const flyOut = (direction: 1 | -1, report: SignalReport): void => {
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
    x.value = withTiming(direction * FLY_OUT, { duration: 220 }, (done) => {
      if (done) {
        runOnJS(direction === 1 ? onStart : onDismiss)(report);
        x.value = 0;
        y.value = 0;
      }
    });
  };

  const swipe = (direction: 1 | -1): void => {
    if (top) flyOut(direction, top);
  };

  const pan = Gesture.Pan()
    .enabled(!expanded && !!top)
    .activeOffsetX([-12, 12])
    .failOffsetY([-16, 16])
    .onChange((event) => {
      x.value = event.translationX;
      y.value = event.translationY * 0.25;
    })
    .onEnd((event) => {
      if (event.translationX > SWIPE_THRESHOLD) {
        runOnJS(swipe)(1);
      } else if (event.translationX < -SWIPE_THRESHOLD) {
        runOnJS(swipe)(-1);
      } else {
        x.value = withSpring(0, { damping: 18, stiffness: 220 });
        y.value = withSpring(0, { damping: 18, stiffness: 220 });
      }
    });

  const toggleExpanded = (): void => {
    const next = !expanded;
    setExpanded(next);
    // Critically damped and quick, like a UIKit sheet, no bounce.
    grow.value = withSpring(next ? 1 : 0, {
      duration: 380,
      dampingRatio: 1,
      overshootClamping: true,
    });
  };

  // The top card lives in a fixed frame; expanding animates that frame out to
  // the full screen so the report opens from where the card sits.
  const topStyle = useAnimatedStyle(() => ({
    position: "absolute",
    left: interpolate(grow.value, [0, 1], [frame.x, 0]),
    top: interpolate(grow.value, [0, 1], [frame.y, 0]),
    width: interpolate(grow.value, [0, 1], [frame.w, width]),
    height: interpolate(grow.value, [0, 1], [frame.h - STACK_PEEK, height]),
    borderRadius: interpolate(grow.value, [0, 1], [CARD_RADIUS, 0]),
    transform: [
      { translateX: x.value },
      { translateY: y.value },
      { rotate: `${interpolate(x.value, [-300, 0, 300], [-10, 0, 10])}deg` },
    ],
  }));
  const startHint = useAnimatedStyle(() => ({
    opacity: interpolate(x.value, [20, SWIPE_THRESHOLD], [0, 1], "clamp"),
  }));
  const dismissHint = useAnimatedStyle(() => ({
    opacity: interpolate(x.value, [-SWIPE_THRESHOLD, -20], [1, 0], "clamp"),
  }));
  // The overlay clips itself, since the card no longer does (its shadow needs
  // to escape).
  const detailStyle = useAnimatedStyle(() => ({
    opacity: interpolate(grow.value, [0.6, 1], [0, 1], "clamp"),
    borderRadius: interpolate(grow.value, [0, 1], [CARD_RADIUS, 0]),
  }));
  const faceStyle = useAnimatedStyle(() => ({
    opacity: interpolate(grow.value, [0, 0.4], [1, 0], "clamp"),
  }));

  return (
    <View style={styles.root} pointerEvents="box-none">
      <View
        style={[styles.frame, { marginTop: headerHeight + 8 }]}
        onLayout={(event) => {
          const {
            x: fx,
            y: fy,
            width: fw,
            height: fh,
          } = event.nativeEvent.layout;
          setFrame({ x: fx, y: fy, w: fw, h: fh });
        }}
      >
        {rest.map((report, index) => (
          <View
            key={report.id}
            style={[
              styles.card,
              styles.behind,
              {
                bottom: STACK_PEEK,
                zIndex: -(index + 1),
                transform: [
                  { scale: 1 - (index + 1) * 0.05 },
                  { translateY: (index + 1) * (STACK_PEEK / 2) + 6 },
                ],
              },
            ]}
          >
            <ReportSummary report={report} />
          </View>
        ))}
      </View>

      {top && frame.w > 0 ? (
        <GestureDetector gesture={pan}>
          <Animated.View style={[styles.card, styles.topCard, topStyle]}>
            <Animated.View
              style={[styles.face, faceStyle]}
              pointerEvents={expanded ? "none" : "auto"}
            >
              <ReportSummary report={top} withEvidence />
              <View style={styles.actions}>
                <CardButton label="Open report" onPress={toggleExpanded} />
              </View>
              <Animated.View style={[styles.hint, styles.hintStart, startHint]}>
                <Text style={styles.hintText}>Start</Text>
              </Animated.View>
              <Animated.View
                style={[styles.hint, styles.hintDismiss, dismissHint]}
              >
                <Text style={styles.hintText}>Dismiss</Text>
              </Animated.View>
            </Animated.View>
            {expanded ? (
              <Animated.View
                style={[
                  StyleSheet.absoluteFill,
                  styles.detail,
                  { paddingTop: insets.top + 64 },
                  detailStyle,
                ]}
              >
                <ReportDetail report={top} />
                <View style={[styles.detailHeader, { top: insets.top + 6 }]}>
                  <GlassCircleButton
                    onPress={toggleExpanded}
                    tint={colors.glassTint}
                  >
                    <Text style={styles.close}>×</Text>
                  </GlassCircleButton>
                </View>
                <View
                  style={[
                    styles.detailActions,
                    { paddingBottom: insets.bottom + 12 },
                  ]}
                >
                  <Glass
                    style={styles.detailActionsGlass}
                    tint={colors.glassTint}
                  >
                    <CardButton
                      label="Dismiss"
                      onPress={() => {
                        toggleExpanded();
                        setTimeout(() => flyOut(-1, top), 250);
                      }}
                    />
                    <CardButton
                      label="Start task"
                      primary
                      disabled={starting}
                      onPress={() => {
                        toggleExpanded();
                        setTimeout(() => flyOut(1, top), 250);
                      }}
                    />
                  </Glass>
                </View>
              </Animated.View>
            ) : null}
          </Animated.View>
        </GestureDetector>
      ) : null}

      {!expanded ? (
        <View style={[styles.footer, { paddingBottom: insets.bottom + 8 }]}>
          <View style={styles.verdict}>
            <GlassCircleButton
              size={64}
              disabled={!top}
              onPress={() => swipe(-1)}
            >
              <Text style={styles.dismissGlyph}>×</Text>
            </GlassCircleButton>
            <Text style={styles.caption}>Dismiss</Text>
          </View>
          <Text style={styles.counter}>{reports.length} to triage</Text>
          <View style={styles.verdict}>
            <GlassCircleButton
              size={64}
              disabled={!top || starting}
              onPress={() => swipe(1)}
            >
              <View style={styles.goClip}>
                <Image
                  source={require("../../assets/hedgehog/idle-strip.png")}
                  style={styles.goSprite}
                />
              </View>
            </GlassCircleButton>
            <Text style={styles.caption}>Start task</Text>
          </View>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0 },
  frame: { flex: 1, marginHorizontal: 16, marginBottom: 12 },
  card: {
    backgroundColor: colors.bgRaised,
    borderRadius: CARD_RADIUS,
    padding: 20,
    shadowColor: "#000",
    shadowOpacity: 0.16,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 14 },
  },
  behind: { position: "absolute", top: 0, left: 0, right: 0 },
  topCard: { justifyContent: "space-between" },
  face: { flex: 1, justifyContent: "space-between" },
  actions: { flexDirection: "row", gap: 8, marginTop: 16 },
  hint: {
    position: "absolute",
    top: 18,
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: radius.pill,
  },
  hintStart: { left: 0, backgroundColor: colors.ok },
  hintDismiss: { right: 0, backgroundColor: colors.inkMute },
  hintText: { fontFamily: fonts.sansBold, fontSize: 13, color: "#FFFFFF" },
  detail: {
    backgroundColor: colors.bgRaised,
    paddingHorizontal: 20,
    overflow: "hidden",
  },
  detailHeader: { position: "absolute", left: 16 },
  detailActions: { position: "absolute", left: 16, right: 16, bottom: 0 },
  detailActionsGlass: {
    flexDirection: "row",
    gap: 8,
    padding: 10,
    borderRadius: radius.pill,
    overflow: "hidden",
  },
  close: { fontSize: 26, lineHeight: 28, color: colors.ink, marginTop: -2 },
  footer: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 32,
  },
  counter: { fontFamily: fonts.sans, fontSize: 14, color: colors.inkMute },
  verdict: { alignItems: "center", gap: 6 },
  caption: {
    fontFamily: fonts.sansMedium,
    fontSize: 12,
    color: colors.inkMute,
  },
  dismissGlyph: {
    fontSize: 34,
    lineHeight: 36,
    color: colors.ink,
    marginTop: -3,
  },
  goClip: { width: 44, height: 44, overflow: "hidden", marginTop: 4 },
  // First idle frame of the 25-frame strip, scaled to sit in the circle.
  goSprite: { width: 44 * 25, height: 44 },
});
