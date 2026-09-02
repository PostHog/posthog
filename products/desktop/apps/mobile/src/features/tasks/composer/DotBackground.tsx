import { StyleSheet, View } from "react-native";
import Svg, { Circle, Defs, Pattern, Rect } from "react-native-svg";
import { useThemeColors } from "@/lib/theme";

/**
 * Subtle tileable dot grid background, matching the desktop new-task screen.
 * Renders absolute-fill behind the composer.
 */
export function DotBackground() {
  const colors = useThemeColors();
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFillObject}>
      <Svg width="100%" height="100%">
        <Defs>
          <Pattern id="dots" patternUnits="userSpaceOnUse" width={8} height={8}>
            <Circle cx={0.8} cy={0.8} r={0.6} fill={colors.gray[6]} />
          </Pattern>
        </Defs>
        <Rect width="100%" height="100%" fill="url(#dots)" />
      </Svg>
    </View>
  );
}
