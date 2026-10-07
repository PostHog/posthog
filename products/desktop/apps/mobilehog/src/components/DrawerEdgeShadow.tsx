import { useDrawerProgress } from "expo-router/drawer";
import { StyleSheet, useWindowDimensions } from "react-native";
import Animated, {
  interpolate,
  type SharedValue,
  useAnimatedStyle,
} from "react-native-reanimated";
import { colors, drawer } from "@/lib/theme";

// The chat layer lives in a native screen that clips its shadow. This ghost
// sits in the drawer exactly where the open chat layer lands, so only its
// shadow shows, and it follows the same rounded corner.
export function DrawerEdgeShadow() {
  const { width, height } = useWindowDimensions();
  const progress = useDrawerProgress() as SharedValue<number>;
  const fade = useAnimatedStyle(() => ({
    opacity: interpolate(progress.value, [0, 1], [0, 1]),
  }));
  return (
    <Animated.View
      pointerEvents="none"
      style={[
        styles.ghost,
        { left: width * drawer.widthFraction, width, height },
        fade,
      ]}
    />
  );
}

const styles = StyleSheet.create({
  ghost: {
    position: "absolute",
    top: 0,
    borderRadius: drawer.sceneRadius,
    backgroundColor: colors.bg,
    shadowColor: "#000",
    shadowOpacity: 0.14,
    shadowRadius: 28,
    shadowOffset: { width: -6, height: 0 },
  },
});
