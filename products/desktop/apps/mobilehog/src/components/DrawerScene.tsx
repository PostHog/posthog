import { useDrawerProgress } from "expo-router/drawer";
import type { ReactNode } from "react";
import { StyleSheet } from "react-native";
import Animated, {
  interpolate,
  type SharedValue,
  useAnimatedStyle,
} from "react-native-reanimated";
import { Glass } from "@/components/Glass";
import { colors, drawer } from "@/lib/theme";

// The chat surface is a frosted layer that slides over the menu: it dims and
// rounds its corner while the drawer is open. Its shadow is painted by the
// drawer (see DrawerEdgeShadow), because the native screen clips to bounds.
export function DrawerScene({ children }: { children: ReactNode }) {
  const progress = useDrawerProgress() as SharedValue<number>;
  const clip = useAnimatedStyle(() => ({
    opacity: interpolate(progress.value, [0, 1], [1, 0.82]),
    borderRadius: interpolate(progress.value, [0, 1], [0, drawer.sceneRadius]),
  }));
  // Solid while closed so the drawer never ghosts through; fades out as the
  // drawer opens to let the glass edge frost it.
  const backing = useAnimatedStyle(() => ({
    opacity: interpolate(progress.value, [0, 1], [1, 0]),
  }));
  return (
    <Animated.View style={[styles.clip, clip]}>
      <Animated.View
        style={[StyleSheet.absoluteFill, styles.backing, backing]}
      />
      <Glass style={styles.scene} tint={colors.sceneTint}>
        {children}
      </Glass>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  clip: { flex: 1, overflow: "hidden" },
  backing: { backgroundColor: colors.bg },
  scene: { flex: 1 },
});
