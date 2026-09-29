import { useRouter } from "expo-router";
import { useState } from "react";
import {
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
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass } from "@/components/Glass";
import { Logomark } from "@/components/Icons";
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

// The landing carousel: three things the app is for, then one way in.
export default function LandingScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [index, setIndex] = useState(0);

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
        <Pressable
          onPress={() => router.push("/signin")}
          style={({ pressed }) => pressed && { opacity: 0.7 }}
        >
          <Glass interactive tint="rgba(255,92,28,0.9)" style={styles.button}>
            <Text style={styles.buttonText}>Get started</Text>
          </Glass>
        </Pressable>
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
});
