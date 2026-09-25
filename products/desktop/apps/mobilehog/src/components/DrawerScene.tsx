import { useDrawerProgress } from "expo-router/drawer";
import type { ReactNode } from "react";
import { StyleSheet } from "react-native";
import Animated, {
  interpolate,
  type SharedValue,
  useAnimatedStyle,
} from "react-native-reanimated";
import { Glass } from "@/components/Glass";
import { drawer } from "@/lib/theme";

// The chat surface is a frosted layer that slides over the menu: it dims and
// rounds its corner while the drawer is open. Its shadow is painted by the
// drawer (see DrawerEdgeShadow), because the native screen clips to bounds.
export function DrawerScene({ children }: { children: ReactNode }) {
  const progress = useDrawerProgress() as SharedValue<number>;
  const clip = useAnimatedStyle(() => ({
    opacity: interpolate(progress.value, [0, 1], [1, 0.82]),
    borderRadius: interpolate(progress.value, [0, 1], [0, drawer.sceneRadius]),
  }));
  return (
    <Animated.View style={[styles.clip, clip]}>
      <Glass style={styles.scene} tint="rgba(244,243,238,0.72)">
        {children}
      </Glass>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  clip: { flex: 1, overflow: "hidden" },
  scene: { flex: 1 },
});
