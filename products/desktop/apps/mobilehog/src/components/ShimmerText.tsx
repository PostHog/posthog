import type React from "react";
import { useEffect, useState } from "react";
import { StyleSheet, Text, type TextStyle, View } from "react-native";
import Animated, {
  Easing,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from "react-native-reanimated";
import { colors } from "@/lib/theme";

// Soft edges come from a few strips of the highlight at rising opacity.
const STRIP_ALPHAS = [0.35, 0.7, 1, 0.7, 0.35];
const STRIP_WIDTH = 24;
const BAND = STRIP_WIDTH * STRIP_ALPHAS.length;

// Muted text with a bright band sweeping across it, the "thinking" shimmer.
// No gradient module needed: a clipped copy of the text rides inside each strip.
export function ShimmerText({
  children,
  style,
}: {
  children: string;
  style?: TextStyle;
}) {
  const [width, setWidth] = useState(0);
  const x = useSharedValue(-BAND);

  useEffect(() => {
    if (width === 0) return;
    x.value = -BAND;
    x.value = withRepeat(
      withTiming(width, { duration: 1400, easing: Easing.linear }),
      -1,
    );
  }, [width, x]);

  return (
    <View
      style={styles.root}
      onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
    >
      <Text style={[style, styles.base]}>{children}</Text>
      {STRIP_ALPHAS.map((alpha, index) => (
        <Strip
          key={String(index)}
          x={x}
          index={index}
          alpha={alpha}
          width={width}
        >
          <Text style={[style, styles.highlight]} numberOfLines={1}>
            {children}
          </Text>
        </Strip>
      ))}
    </View>
  );
}

function Strip({
  x,
  index,
  alpha,
  width,
  children,
}: {
  x: { value: number };
  index: number;
  alpha: number;
  width: number;
  children: React.ReactNode;
}) {
  const offset = index * STRIP_WIDTH;
  const window = useAnimatedStyle(() => ({
    transform: [{ translateX: x.value + offset }],
  }));
  // The copy keeps the full text width so the strip clips rather than wraps it.
  const content = useAnimatedStyle(() => ({
    width,
    transform: [{ translateX: -(x.value + offset) }],
  }));
  return (
    <Animated.View
      pointerEvents="none"
      style={[styles.strip, { opacity: alpha }, window]}
    >
      <Animated.View style={content}>{children}</Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  root: { alignSelf: "flex-start", overflow: "hidden" },
  base: { color: colors.inkSoft },
  highlight: { color: colors.inkMute },
  strip: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: 0,
    width: STRIP_WIDTH,
    overflow: "hidden",
  },
});
