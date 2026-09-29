import { StyleSheet, Text, View } from "react-native";
import { useConnectivity } from "@/lib/offline";
import { colors, fonts } from "@/lib/theme";

export function ConnectionBanner() {
  const online = useConnectivity((state) => state.online);
  if (online) return null;
  return (
    <View style={styles.banner}>
      <Text accessibilityRole="alert" style={styles.text}>
        Offline. Saved content is available. Send your draft when you reconnect.
      </Text>
    </View>
  );
}
const styles = StyleSheet.create({
  banner: {
    paddingHorizontal: 18,
    paddingVertical: 8,
    backgroundColor: colors.surface,
  },
  text: { fontFamily: fonts.sans, fontSize: 13, color: colors.inkSoft },
});
