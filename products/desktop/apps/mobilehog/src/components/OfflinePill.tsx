import { StyleSheet, Text, View } from "react-native";
import Animated, { FadeInUp, FadeOutUp } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass } from "@/components/Glass";
import { useOnline } from "@/lib/network";
import { colors, fonts, radius } from "@/lib/theme";

export function OfflinePill() {
  const online = useOnline((s) => s.online);
  const insets = useSafeAreaInsets();
  if (online) return null;
  return (
    <View style={[styles.root, { top: insets.top + 4 }]} pointerEvents="none">
      <Animated.View entering={FadeInUp.duration(220)} exiting={FadeOutUp}>
        <Glass style={styles.pill}>
          <View style={styles.dot} />
          <Text style={styles.text}>Offline · showing saved</Text>
        </Glass>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { position: "absolute", left: 0, right: 0, alignItems: "center" },
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.pill,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: colors.inkMute,
  },
  text: { fontFamily: fonts.sansMedium, fontSize: 13, color: colors.inkSoft },
});
