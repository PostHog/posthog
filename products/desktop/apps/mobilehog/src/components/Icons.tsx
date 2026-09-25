import { type ColorValue, Image, StyleSheet, Text, View } from "react-native";
import { colors, fonts } from "@/lib/theme";

// Tiny hand-drawn glyphs so the app has no icon dependency.

export function MenuIcon({ color = colors.ink }: { color?: ColorValue }) {
  return (
    <View style={styles.menu}>
      <View style={[styles.bar, { width: 18, backgroundColor: color }]} />
      <View style={[styles.bar, { width: 12, backgroundColor: color }]} />
      <View style={[styles.bar, { width: 15, backgroundColor: color }]} />
    </View>
  );
}

export function ArrowUpIcon({
  color = colors.darkText,
}: {
  color?: ColorValue;
}) {
  return <Text style={[styles.glyph, { color }]}>↑</Text>;
}

export function StopIcon({ color = colors.darkText }: { color?: ColorValue }) {
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
  color?: ColorValue;
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

export function BellIcon({ color = colors.ink }: { color?: ColorValue }) {
  return (
    <View style={styles.bell}>
      <View style={[styles.bellBody, { borderColor: color }]} />
      <View style={[styles.bellClapper, { backgroundColor: color }]} />
    </View>
  );
}

export function SteeringIcon({ color = colors.ink }: { color?: ColorValue }) {
  return (
    <View style={styles.steer}>
      <View style={[styles.steerRing, { borderColor: color }]} />
      <View style={[styles.steerHub, { backgroundColor: color }]} />
    </View>
  );
}

export function CardsIcon({ color = colors.ink }: { color?: ColorValue }) {
  return (
    <View style={styles.cards}>
      <View style={[styles.cardBack, { borderColor: color }]} />
      <View style={[styles.cardFront, { borderColor: color }]} />
    </View>
  );
}

// A rubbish bin: handle, lid, then the body with two slats.
export function BinIcon({ color = colors.ink }: { color?: ColorValue }) {
  return (
    <View style={styles.bin}>
      <View style={[styles.binHandle, { borderColor: color }]} />
      <View style={[styles.binLid, { backgroundColor: color }]} />
      <View style={[styles.binBody, { borderColor: color }]}>
        <View style={[styles.binSlat, { backgroundColor: color }]} />
        <View style={[styles.binSlat, { backgroundColor: color }]} />
      </View>
    </View>
  );
}

// A speech bubble with a plus inside: start a new chat.
export function NewChatIcon({ color = colors.ink }: { color?: ColorValue }) {
  return (
    <View style={styles.bubbleWrap}>
      <View style={[styles.bubble, { borderColor: color }]}>
        <View style={[styles.plusBar, { backgroundColor: color }]} />
        <View
          style={[
            styles.plusBar,
            { backgroundColor: color, transform: [{ rotate: "90deg" }] },
          ]}
        />
      </View>
      <View style={styles.bubbleTailClip}>
        <View style={[styles.bubbleTail, { backgroundColor: color }]} />
      </View>
    </View>
  );
}

export function LockIcon({ color = colors.inkSoft }: { color?: ColorValue }) {
  return (
    <View style={styles.lock}>
      <View style={[styles.lockShackle, { borderColor: color }]} />
      <View style={[styles.lockBody, { borderColor: color }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  bubbleWrap: { width: 24, height: 24 },
  bubble: {
    width: 22,
    height: 19,
    borderWidth: 2.2,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  plusBar: { position: "absolute", width: 9, height: 2.2, borderRadius: 1 },
  // The tail is the bottom half of a rotated square, clipped below the bubble.
  bubbleTailClip: {
    position: "absolute",
    left: 4,
    top: 17,
    width: 10,
    height: 6,
    overflow: "hidden",
  },
  bubbleTail: {
    position: "absolute",
    left: 1,
    top: -5,
    width: 7,
    height: 7,
    transform: [{ rotate: "45deg" }],
  },
  bin: { alignItems: "center" },
  binHandle: {
    width: 10,
    height: 5,
    borderWidth: 2.5,
    borderBottomWidth: 0,
    borderTopLeftRadius: 3,
    borderTopRightRadius: 3,
  },
  binLid: { width: 24, height: 2.5, borderRadius: 2 },
  binBody: {
    width: 18,
    height: 18,
    marginTop: 2,
    borderWidth: 2.5,
    borderTopWidth: 0,
    borderBottomLeftRadius: 5,
    borderBottomRightRadius: 5,
    flexDirection: "row",
    justifyContent: "space-evenly",
    paddingTop: 2,
  },
  binSlat: { width: 2.5, height: 9, borderRadius: 2 },
  menu: { gap: 3.5, alignItems: "flex-start" },
  bar: { height: 2, borderRadius: 1 },
  glyph: { fontSize: 20, fontFamily: fonts.sansBold, marginTop: -1 },
  stop: { width: 14, height: 14, borderRadius: 3 },
  lock: { width: 14, height: 14, alignItems: "center" },
  cards: { width: 22, height: 20 },
  cardBack: {
    position: "absolute",
    left: 6,
    top: 0,
    width: 12,
    height: 16,
    borderWidth: 1.8,
    borderRadius: 3,
    transform: [{ rotate: "12deg" }],
  },
  cardFront: {
    position: "absolute",
    left: 1,
    top: 2,
    width: 12,
    height: 16,
    borderWidth: 1.8,
    borderRadius: 3,
    backgroundColor: colors.bg,
    transform: [{ rotate: "-8deg" }],
  },
  steer: {
    width: 20,
    height: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  steerRing: { width: 18, height: 18, borderRadius: 9, borderWidth: 1.8 },
  steerHub: { position: "absolute", width: 6, height: 6, borderRadius: 3 },
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
