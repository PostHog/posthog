import * as Haptics from "expo-haptics";
import { router } from "expo-router";
import { useDrawerProgress } from "expo-router/drawer";
import type { ReactNode } from "react";
import { StyleSheet, View } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, {
  interpolate,
  runOnJS,
  type SharedValue,
  useAnimatedStyle,
  useSharedValue,
} from "react-native-reanimated";
import { useNavHistory } from "@/lib/history";
import { colors, drawer } from "@/lib/theme";

function swipeNavigate(direction: "back" | "forward"): void {
  const { goBack, goForward } = useNavHistory.getState();
  const target = direction === "back" ? goBack() : goForward();
  if (!target) return;
  Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
  router.navigate(target as never);
}

// The drawer paints the shadow because the native screen clips to bounds.
export function DrawerScene({ children }: { children: ReactNode }) {
  const progress = useDrawerProgress() as SharedValue<number>;
  const startX = useSharedValue(0);
  const clip = useAnimatedStyle(() => ({
    opacity: interpolate(progress.value, [0, 1], [1, 0.82]),
    borderRadius: interpolate(progress.value, [0, 1], [0, drawer.sceneRadius]),
  }));
  // Fade the shared background with the scene when the drawer opens.
  const backing = useAnimatedStyle(() => ({
    opacity: interpolate(progress.value, [0, 1], [1, 0]),
  }));
  // Swipe right for back, left for forward. The high activation offset lets
  // horizontal children (triage cards at 12px) win the gesture race, and the
  // start-x guard leaves the left edge to the drawer-open gesture.
  const swipe = Gesture.Pan()
    .activeOffsetX([-40, 40])
    .failOffsetY([-20, 20])
    .onBegin((event) => {
      startX.value = event.x;
    })
    .onEnd((event) => {
      if (event.translationX > 70 && startX.value > drawer.swipeEdgeWidth) {
        runOnJS(swipeNavigate)("back");
      } else if (event.translationX < -70) {
        runOnJS(swipeNavigate)("forward");
      }
    });
  return (
    <GestureDetector gesture={swipe}>
      <Animated.View style={[styles.clip, clip]}>
        <Animated.View
          style={[StyleSheet.absoluteFill, styles.backing, backing]}
        />
        <View style={styles.scene}>{children}</View>
      </Animated.View>
    </GestureDetector>
  );
}

const styles = StyleSheet.create({
  clip: { flex: 1, overflow: "hidden" },
  backing: { backgroundColor: colors.bg },
  scene: { flex: 1 },
});
