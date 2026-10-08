import { useEffect, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import Animated, {
  FadeIn,
  FadeInUp,
  FadeOutUp,
  LinearTransition,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass } from "@/components/Glass";
import { useOnline } from "@/lib/network";
import { colors, fonts, radius } from "@/lib/theme";

const BACK_ONLINE_MS = 2000;

export function OfflinePill() {
  const online = useOnline((s) => s.online);
  const insets = useSafeAreaInsets();
  const [backOnline, setBackOnline] = useState(false);
  const wasOffline = useRef(false);

  // Confirms the reconnect for a moment before the pill leaves.
  useEffect(() => {
    if (!online) {
      wasOffline.current = true;
      setBackOnline(false);
      return;
    }
    if (!wasOffline.current) return;
    wasOffline.current = false;
    setBackOnline(true);
    const timer = setTimeout(() => setBackOnline(false), BACK_ONLINE_MS);
    return () => clearTimeout(timer);
  }, [online]);

  if (online && !backOnline) return null;
  return (
    <View style={[styles.root, { top: insets.top + 4 }]} pointerEvents="none">
      <Animated.View
        entering={FadeInUp.duration(220)}
        exiting={FadeOutUp.duration(220)}
        layout={LinearTransition.duration(220)}
      >
        <Glass style={styles.pill}>
          <View
            style={[
              styles.dot,
              { backgroundColor: online ? colors.ok : colors.danger },
            ]}
          />
          <Animated.Text
            key={online ? "online" : "offline"}
            entering={FadeIn.duration(200)}
            style={styles.text}
          >
            {online ? "Back online" : "Offline"}
          </Animated.Text>
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
  },
  text: { fontFamily: fonts.sansMedium, fontSize: 13, color: colors.inkSoft },
});
