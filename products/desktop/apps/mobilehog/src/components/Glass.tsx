import { GlassView, isLiquidGlassAvailable } from "expo-glass-effect";
import type { ReactNode } from "react";
import {
  Pressable,
  type StyleProp,
  StyleSheet,
  View,
  type ViewStyle,
} from "react-native";
import { colors } from "@/lib/theme";

const liquid = isLiquidGlassAvailable();

interface GlassProps {
  children?: ReactNode;
  style?: StyleProp<ViewStyle>;
  interactive?: boolean;
  tint?: string;
}

// Real Liquid Glass on iOS 26, a translucent card everywhere else.
export function Glass({ children, style, interactive, tint }: GlassProps) {
  if (liquid) {
    return (
      <GlassView
        glassEffectStyle="regular"
        isInteractive={interactive}
        tintColor={tint}
        style={style}
      >
        {children}
      </GlassView>
    );
  }
  return <View style={[styles.fallback, style]}>{children}</View>;
}

interface GlassButtonProps {
  children: ReactNode;
  onPress: () => void;
  size?: number;
  disabled?: boolean;
  tint?: string;
  style?: StyleProp<ViewStyle>;
}

export function GlassCircleButton({
  children,
  onPress,
  size = 46,
  disabled,
  tint,
  style,
}: GlassButtonProps) {
  return (
    <Pressable onPress={onPress} disabled={disabled} hitSlop={8}>
      {({ pressed }) => (
        <Glass
          interactive
          tint={tint}
          style={[
            styles.circle,
            {
              width: size,
              height: size,
              borderRadius: size / 2,
              opacity: pressed ? 0.7 : 1,
            },
            style,
          ]}
        >
          {children}
        </Glass>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  fallback: {
    backgroundColor: colors.glass,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(255,255,255,0.8)",
    shadowColor: "#000",
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
  },
  circle: {
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
});
