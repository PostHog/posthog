import { useEffect } from "react";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSequence,
  withTiming,
} from "react-native-reanimated";

interface LiveDotProps {
  /** True while a background fetch is in flight */
  active: boolean;
  /** True when there's a network/fetch error */
  hasError?: boolean;
}

/**
 * Strobing red dot that indicates the inbox is live-polling.
 * Pulses brighter/larger when actively fetching, dims when idle.
 */
const COLOR_LIVE = "#e5484d";
const COLOR_ERROR = "#f5a623";

export function LiveDot({ active, hasError }: LiveDotProps) {
  const color = hasError ? COLOR_ERROR : COLOR_LIVE;
  const scale = useSharedValue(0.92);
  const opacity = useSharedValue(0.5);

  useEffect(() => {
    if (active) {
      scale.value = withRepeat(
        withSequence(
          withTiming(1.15, { duration: 400 }),
          withTiming(0.92, { duration: 400 }),
        ),
        -1,
        true,
      );
      opacity.value = withRepeat(
        withSequence(
          withTiming(1, { duration: 400 }),
          withTiming(0.5, { duration: 400 }),
        ),
        -1,
        true,
      );
    } else {
      scale.value = withTiming(0.92, { duration: 600 });
      opacity.value = withTiming(0.5, { duration: 600 });
    }
  }, [active, scale, opacity]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
    opacity: opacity.value,
  }));

  return (
    <Animated.View
      style={[
        {
          width: 7,
          height: 7,
          borderRadius: 3.5,
          backgroundColor: color,
        },
        animatedStyle,
      ]}
    />
  );
}
