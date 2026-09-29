import { Image, StyleSheet, Text, View } from "react-native";
import { colors, fonts } from "@/lib/theme";

// Tiny hand-drawn glyphs so the app has no icon dependency.

export function MenuIcon({ color = colors.ink }: { color?: string }) {
  return (
    <View style={styles.menu}>
      <View style={[styles.bar, { width: 18, backgroundColor: color }]} />
      <View style={[styles.bar, { width: 12, backgroundColor: color }]} />
      <View style={[styles.bar, { width: 15, backgroundColor: color }]} />
    </View>
  );
}

export function ArrowUpIcon({ color = colors.darkText }: { color?: string }) {
  return <Text style={[styles.glyph, { color }]}>↑</Text>;
}

export function StopIcon({ color = colors.darkText }: { color?: string }) {
  return <View style={[styles.stop, { backgroundColor: color }]} />;
}

export function Logomark({ size = 56 }: { size?: number }) {
  return (
    <Image
      source={require("../../assets/logomark.png")}
      style={{ width: size, height: size }}
      resizeMode="contain"
    />
  );
}

// Desktop's task status dot: solid for live states, a hollow ring otherwise.
export function Dot({
  color = colors.inkMute,
  size = 8,
  hollow = false,
}: {
  color?: string;
  size?: number;
  hollow?: boolean;
}) {
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: hollow ? "transparent" : color,
        borderWidth: hollow ? 1.5 : 0,
        borderColor: color,
      }}
    />
  );
}

export function BellIcon({ color = colors.ink }: { color?: string }) {
  return (
    <View style={styles.bell}>
      <View style={[styles.bellBody, { borderColor: color }]} />
      <View style={[styles.bellClapper, { backgroundColor: color }]} />
    </View>
  );
}

export function LockIcon({ color = colors.inkSoft }: { color?: string }) {
  return (
    <View style={styles.lock}>
      <View style={[styles.lockShackle, { borderColor: color }]} />
      <View style={[styles.lockBody, { borderColor: color }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  menu: { gap: 3.5, alignItems: "flex-start" },
  bar: { height: 2, borderRadius: 1 },
  glyph: { fontSize: 20, fontFamily: fonts.sansBold, marginTop: -1 },
  stop: { width: 14, height: 14, borderRadius: 3 },
  lock: { width: 14, height: 14, alignItems: "center" },
  bell: {
    width: 20,
    height: 20,
    alignItems: "center",
    justifyContent: "flex-end",
  },
  bellBody: {
    width: 14,
    height: 14,
    borderWidth: 1.8,
    borderTopLeftRadius: 7,
    borderTopRightRadius: 7,
    borderBottomLeftRadius: 2,
    borderBottomRightRadius: 2,
  },
  bellClapper: { width: 5, height: 2.5, borderRadius: 2, marginTop: 1 },
  lockShackle: {
    width: 8,
    height: 6,
    borderWidth: 1.5,
    borderBottomWidth: 0,
    borderTopLeftRadius: 4,
    borderTopRightRadius: 4,
  },
  lockBody: { width: 12, height: 8, borderWidth: 1.5, borderRadius: 2 },
});
