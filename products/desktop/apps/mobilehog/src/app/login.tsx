import { useState } from "react";
import {
  ActivityIndicator,
  Image,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
} from "react-native";
import Animated, {
  useAnimatedStyle,
  withSpring,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass } from "@/components/Glass";
import { Logomark } from "@/components/Icons";
import { DEV_EMAIL, DEV_PASSWORD } from "@/config";
import { useAuth } from "@/lib/auth";
import type { CloudRegion } from "@/lib/oauth";
import { colors, fonts, radius } from "@/lib/theme";

const SLIDES = [
  {
    image: require("../../assets/hoggies/remote-work.png"),
    title: "Code on the go",
    body: "Kick off a task from the couch and watch the agent work through it, tool call by tool call.",
  },
  {
    image: require("../../assets/hoggies/im-the-driver.png"),
    title: "Steer your self-driving agents",
    body: "Swipe through what the agents found overnight. Dismiss the noise, start a task on the rest.",
  },
  {
    image: require("../../assets/hoggies/coding-group.png"),
    title: "See what your team is shipping",
    body: "Every space, every task, every finished run, in one feed you can read between meetings.",
  },
];

const REGIONS: Array<{ key: CloudRegion; label: string }> = [
  { key: "us", label: "🇺🇸  US Cloud" },
  { key: "eu", label: "🇪🇺  EU Cloud" },
];

const SEGMENT_PAD = 4;

// A glass pill that slides under the chosen region.
function RegionSegment({
  value,
  onChange,
}: {
  value: CloudRegion;
  onChange: (region: CloudRegion) => void;
}) {
  const [width, setWidth] = useState(0);
  const item = (width - SEGMENT_PAD * 2) / REGIONS.length;
  const index = REGIONS.findIndex((option) => option.key === value);
  const slide = useAnimatedStyle(() => ({
    width: item,
    transform: [
      {
        translateX: withSpring(index * item, {
          duration: 420,
          dampingRatio: 0.85,
        }),
      },
    ],
  }));
  return (
    <Glass
      style={styles.segment}
      tint={colors.fill}
      onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
    >
      {width > 0 ? (
        <Animated.View style={[styles.segmentPill, slide]}>
          <Glass interactive style={styles.pillGlass} />
        </Animated.View>
      ) : null}
      {REGIONS.map((option) => {
        const active = option.key === value;
        return (
          <Pressable
            key={option.key}
            onPress={() => onChange(option.key)}
            style={styles.segmentItem}
          >
            <Text
              style={[styles.segmentText, active && styles.segmentTextActive]}
            >
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </Glass>
  );
}

// The landing carousel: three things the app is for, then straight into
// PostHog's own login sheet, which handles passwords, Google, GitHub and SSO.
export default function LandingScreen() {
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [index, setIndex] = useState(0);
  const login = useAuth((s) => s.login);
  const loginWithOAuth = useAuth((s) => s.loginWithOAuth);
  const [region, setRegion] = useState<CloudRegion>("us");
  const [busy, setBusy] = useState<"cloud" | "local" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (
    kind: "cloud" | "local",
    attempt: () => Promise<void>,
  ): Promise<void> => {
    if (busy) return;
    setBusy(kind);
    setError(null);
    try {
      await attempt();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const onScrollEnd = (event: NativeSyntheticEvent<NativeScrollEvent>): void =>
    setIndex(Math.round(event.nativeEvent.contentOffset.x / width));

  return (
    <View style={styles.root}>
      <View style={[styles.brand, { paddingTop: insets.top + 24 }]}>
        <Logomark size={36} />
        <Text style={styles.wordmark}>PostHog</Text>
      </View>
      <ScrollView
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={onScrollEnd}
        style={styles.pager}
      >
        {SLIDES.map((slide) => (
          <View key={slide.title} style={[styles.slide, { width }]}>
            <Image
              source={slide.image}
              style={styles.hoggie}
              resizeMode="contain"
            />
            <Text style={styles.title}>{slide.title}</Text>
            <Text style={styles.body}>{slide.body}</Text>
          </View>
        ))}
      </ScrollView>
      <View style={[styles.footer, { paddingBottom: insets.bottom + 20 }]}>
        <View style={styles.dots}>
          {SLIDES.map((slide, i) => (
            <View
              key={slide.title}
              style={[styles.dot, i === index && styles.dotActive]}
            />
          ))}
        </View>
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <RegionSegment value={region} onChange={setRegion} />
        <Pressable
          onPress={() => run("cloud", () => loginWithOAuth(region))}
          disabled={!!busy}
          style={({ pressed }) => [
            busy === "local" && { opacity: 0.4 },
            pressed && { opacity: 0.7 },
          ]}
        >
          <Glass interactive tint="rgba(255,92,28,0.9)" style={styles.button}>
            {busy === "cloud" ? (
              <ActivityIndicator color="#FFFFFF" />
            ) : (
              <Text style={styles.buttonText}>Get started</Text>
            )}
          </Glass>
        </Pressable>
        {__DEV__ ? (
          <Pressable
            onPress={() => run("local", () => login(DEV_EMAIL, DEV_PASSWORD))}
            disabled={!!busy}
            style={styles.devLink}
          >
            {busy === "local" ? (
              <ActivityIndicator size="small" color={colors.inkMute} />
            ) : (
              <Text style={styles.link}>Sign in to localhost</Text>
            )}
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  brand: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
  },
  wordmark: { fontFamily: fonts.serif, fontSize: 24, color: colors.ink },
  pager: { flex: 1 },
  slide: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 36,
    gap: 14,
  },
  hoggie: { width: 260, height: 260, marginBottom: 10 },
  title: {
    fontFamily: fonts.sansBold,
    fontSize: 28,
    lineHeight: 34,
    color: colors.ink,
    textAlign: "center",
  },
  body: {
    fontFamily: fonts.sans,
    fontSize: 16,
    lineHeight: 23,
    color: colors.inkSoft,
    textAlign: "center",
  },
  footer: { paddingHorizontal: 28, gap: 22 },
  dots: { flexDirection: "row", justifyContent: "center", gap: 8 },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.line,
  },
  dotActive: { backgroundColor: colors.ink, width: 22 },
  button: {
    borderRadius: radius.pill,
    paddingVertical: 17,
    alignItems: "center",
    overflow: "hidden",
  },
  buttonText: { color: "#FFFFFF", fontSize: 17, fontFamily: fonts.sansSemi },
  error: {
    color: colors.danger,
    fontFamily: fonts.sans,
    fontSize: 13,
    lineHeight: 18,
    textAlign: "center",
  },
  segment: {
    flexDirection: "row",
    borderRadius: radius.pill,
    padding: SEGMENT_PAD,
    overflow: "hidden",
    marginBottom: -8,
  },
  segmentPill: {
    position: "absolute",
    top: SEGMENT_PAD,
    bottom: SEGMENT_PAD,
    left: SEGMENT_PAD,
  },
  pillGlass: { flex: 1, borderRadius: radius.pill, overflow: "hidden" },
  segmentItem: {
    flex: 1,
    paddingVertical: 10,
    alignItems: "center",
  },
  segmentText: {
    fontFamily: fonts.sansMedium,
    fontSize: 15,
    color: colors.inkMute,
  },
  segmentTextActive: { color: colors.ink },
  devLink: { alignItems: "center", marginTop: -6 },
  link: { fontFamily: fonts.sansMedium, fontSize: 14, color: colors.inkMute },
});
