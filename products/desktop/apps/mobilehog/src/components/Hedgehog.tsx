import { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useDerivedValue,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";

// Sprite strips from @posthog/hedgehog-mode's default skin, 80px frames.
const WALK = {
  source: require("../../assets/hedgehog/walk-strip.png"),
  frames: 11,
  fps: 30,
};
const IDLE = {
  source: require("../../assets/hedgehog/idle-strip.png"),
  frames: 25,
  fps: 6,
};

const SIZE = 56;
const SPEED = 70; // px per second

interface HedgehogProps {
  walking: boolean;
}

// Paces back and forth while the agent thinks or runs tools, idles otherwise.
// Everything animates on the UI thread, so the JS thread stays free for input.
export function Hedgehog({ walking }: HedgehogProps) {
  const [width, setWidth] = useState(0);
  const anim = walking ? WALK : IDLE;
  const frame = useSharedValue(0);
  const x = useSharedValue(0);
  const previous = useSharedValue(0);
  const heading = useSharedValue(1);

  useEffect(() => {
    frame.value = 0;
    frame.value = withRepeat(
      withTiming(anim.frames, {
        duration: (anim.frames / anim.fps) * 1000,
        easing: Easing.linear,
      }),
      -1,
    );
    return () => cancelAnimation(frame);
  }, [anim, frame]);

  useEffect(() => {
    const max = Math.max(0, width - SIZE);
    if (!walking || max === 0) {
      cancelAnimation(x);
      return;
    }
    // Finish the current leg from wherever we are, then bounce between the edges.
    const toEnd = ((max - x.value) / SPEED) * 1000;
    const leg = (max / SPEED) * 1000;
    x.value = withSequence(
      withTiming(max, { duration: toEnd, easing: Easing.linear }),
      withRepeat(
        withSequence(
          withTiming(0, { duration: leg, easing: Easing.linear }),
          withTiming(max, { duration: leg, easing: Easing.linear }),
        ),
        -1,
      ),
    );
  }, [walking, width, x]);

  // Face the direction of travel; the sprites are drawn facing right.
  const facing = useDerivedValue(() => {
    if (x.value !== previous.value) {
      heading.value = x.value > previous.value ? 1 : -1;
      previous.value = x.value;
    }
    return heading.value;
  });
  const sprite = useAnimatedStyle(() => ({
    transform: [{ translateX: x.value }, { scaleX: facing.value }],
  }));
  const strip = useAnimatedStyle(() => ({
    transform: [{ translateX: -Math.floor(frame.value % anim.frames) * SIZE }],
  }));

  return (
    <View
      style={styles.track}
      onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
      pointerEvents="none"
    >
      <Animated.View style={[styles.sprite, sprite]}>
        <Animated.Image
          source={anim.source}
          style={[{ width: SIZE * anim.frames, height: SIZE }, strip]}
        />
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  track: { height: SIZE, marginBottom: -6, zIndex: 1 },
  sprite: { width: SIZE, height: SIZE, overflow: "hidden" },
});
