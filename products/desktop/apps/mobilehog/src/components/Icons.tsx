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

export function Dot({
  color = colors.inkMute,
  size = 7,
}: {
  color?: string;
  size?: number;
}) {
  return (
    <View
      style={{
        width: size,
        height: size,
        borderRadius: size / 2,
        backgroundColor: color,
      }}
    />
  );
}

const styles = StyleSheet.create({
  menu: { gap: 3.5, alignItems: "flex-start" },
  bar: { height: 2, borderRadius: 1 },
  glyph: { fontSize: 20, fontFamily: fonts.sansBold, marginTop: -1 },
  stop: { width: 14, height: 14, borderRadius: 3 },
});
