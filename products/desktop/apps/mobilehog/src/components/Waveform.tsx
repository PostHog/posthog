import { useState } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  type SharedValue,
  useAnimatedStyle,
  useSharedValue,
} from "react-native-reanimated";
import { colors } from "@/lib/theme";

export const SAMPLE_MS = 80;
// Ring of recent levels, larger than the widest strip in steps.
export const RING = 96;
const BAR = 3;
const STEP = BAR + 4;
const HEIGHT = 22;
// Share of the strip over which bars grow in at the right and shrink out at the left.
const FADE_IN = 0.06;
const FADE_OUT = 0.08;

function envelope(position: number): number {
  "worklet";
  return Math.max(
    0,
    Math.min(1, (1 - position) / FADE_IN, position / FADE_OUT),
  );
}

// Slot k shows the sample k steps behind the head; slot -1 is the one entering.
function Bar({
  slot,
  levels,
  head,
  width,
}: {
  slot: number;
  levels: SharedValue<number[]>;
  head: SharedValue<number>;
  width: SharedValue<number>;
}) {
  const style = useAnimatedStyle(() => {
    const id = Math.floor(head.value) - slot;
    const level = id >= 0 ? levels.value[id % RING] : -1;
    const x = width.value - STEP / 2 - (head.value - id) * STEP;
    const size = level < 0 ? 0 : level < 0.08 ? BAR : BAR + level * HEIGHT;
    const height = width.value > 0 ? size * envelope(x / width.value) : 0;
    const barWidth = Math.min(BAR, height);
    return {
      height,
      width: barWidth,
      transform: [
        { translateX: x - barWidth / 2 },
        { translateY: (HEIGHT + BAR - height) / 2 },
      ],
    };
  });
  return <Animated.View style={[styles.bar, style]} />;
}

// Renders once; every frame reads levels and the gliding head on the UI thread.
export function Waveform({
  levels,
  head,
}: {
  levels: SharedValue<number[]>;
  head: SharedValue<number>;
}) {
  const width = useSharedValue(0);
  const [slots, setSlots] = useState(0);
  return (
    <View
      style={styles.root}
      onLayout={(event) => {
        width.value = event.nativeEvent.layout.width;
        setSlots(Math.ceil(event.nativeEvent.layout.width / STEP) + 1);
      }}
    >
      {Array.from({ length: slots + 1 }, (_, index) => (
        <Bar
          key={String(index)}
          slot={index - 1}
          levels={levels}
          head={head}
          width={width}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, height: HEIGHT + BAR, overflow: "hidden" },
  bar: {
    position: "absolute",
    left: 0,
    top: 0,
    borderRadius: BAR / 2,
    backgroundColor: colors.ink,
  },
});
