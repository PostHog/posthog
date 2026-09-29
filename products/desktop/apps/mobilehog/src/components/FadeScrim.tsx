import { type StyleProp, StyleSheet, View, type ViewStyle } from "react-native";
import { colors } from "@/lib/theme";

const STRIPS = 28;

// Fades content out under the composer: clear at the top, solid at the
// bottom. Stacked strips stand in for a gradient so no native module is needed.
export function FadeScrim({
  style,
  color = colors.bg,
}: {
  style?: StyleProp<ViewStyle>;
  color?: string;
}) {
  return (
    <View pointerEvents="none" style={[styles.root, style]}>
      {Array.from({ length: STRIPS }, (_, index) => {
        const t = (index + 1) / STRIPS;
        return (
          <View
            key={String(index)}
            style={{
              flex: 1,
              backgroundColor: color,
              opacity: Math.min(1, t * t * 1.05),
            }}
          />
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flexDirection: "column" },
});
