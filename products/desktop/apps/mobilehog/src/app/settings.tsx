import { useRouter } from "expo-router";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from "react-native";
import { GlassCircleButton } from "@/components/Glass";
import { useAuth } from "@/lib/auth";
import { type AppearanceMode, usePrefs } from "@/lib/prefs";
import { colors, fonts, radius } from "@/lib/theme";

export default function SettingsSheet() {
  const router = useRouter();
  const session = useAuth((s) => s.session);
  const logout = useAuth((s) => s.logout);
  const hedgehogMode = usePrefs((s) => s.hedgehogMode);
  const appearance = usePrefs((s) => s.appearance);
  const setPrefs = usePrefs((s) => s.set);
  const initials = (session?.userName ?? "").slice(0, 2).toUpperCase();

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.content}>
      <View style={styles.header}>
        <GlassCircleButton size={44} onPress={() => router.back()}>
          <Text style={styles.close}>×</Text>
        </GlassCircleButton>
        <Text style={styles.title}>Settings</Text>
        <View style={{ width: 44 }} />
      </View>

      <View style={styles.card}>
        <View style={styles.accountRow}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{initials}</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.email} numberOfLines={1}>
              {session?.email ?? session?.userName}
            </Text>
            <Text style={styles.sub} numberOfLines={1}>
              {session?.projectName}
              {session
                ? ` · ${session.region === "local" ? "Local" : session.region.toUpperCase()}`
                : ""}
            </Text>
          </View>
        </View>
      </View>

      <Text style={styles.section}>Appearance</Text>
      <View style={styles.card}>
        <View style={styles.modes}>
          {MODES.map((mode) => (
            <ModeOption
              key={mode.value}
              mode={mode}
              selected={appearance === mode.value}
              onPress={() => setPrefs({ appearance: mode.value })}
            />
          ))}
        </View>
        <View style={[styles.row, styles.rowDivided]}>
          <Text style={styles.rowLabel}>Hedgehog mode</Text>
          <Switch
            value={hedgehogMode}
            onValueChange={(value) => setPrefs({ hedgehogMode: value })}
            trackColor={{ true: colors.accent }}
          />
        </View>
      </View>

      <Pressable
        onPress={async () => {
          router.back();
          await logout();
        }}
        style={({ pressed }) => [styles.logout, pressed && { opacity: 0.7 }]}
      >
        <Text style={styles.logoutText}>Log out</Text>
      </Pressable>
    </ScrollView>
  );
}

const MODES: { value: AppearanceMode; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

// A tiny phone-screen mockup for each scheme; System is split diagonally.
function ModeOption({
  mode,
  selected,
  onPress,
}: {
  mode: (typeof MODES)[number];
  selected: boolean;
  onPress: () => void;
}) {
  const Half = ({ dark }: { dark: boolean }) => (
    <View style={[styles.thumb, dark ? styles.thumbDark : styles.thumbLight]}>
      <View style={[styles.thumbCard, dark && styles.thumbCardDark]}>
        <View style={[styles.thumbLine, { width: 36 }]} />
        <View style={[styles.thumbLine, { width: 26 }]} />
        <View style={styles.thumbDot} />
      </View>
    </View>
  );
  return (
    <Pressable onPress={onPress} style={styles.mode}>
      <View style={[styles.thumbFrame, selected && styles.thumbSelected]}>
        <Half dark={mode.value === "dark"} />
        {mode.value === "system" ? (
          <View style={styles.diagonal}>
            <View style={styles.diagonalInner}>
              <Half dark />
            </View>
          </View>
        ) : null}
      </View>
      <Text style={[styles.modeLabel, selected && styles.modeLabelSelected]}>
        {mode.label}
      </Text>
    </Pressable>
  );
}

const THUMB_W = 96;
const THUMB_H = 64;

const styles = StyleSheet.create({
  modes: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 14,
    paddingHorizontal: 2,
  },
  mode: { alignItems: "center", gap: 8 },
  thumbFrame: {
    width: THUMB_W,
    height: THUMB_H,
    borderRadius: 14,
    overflow: "hidden",
    borderWidth: 2,
    borderColor: "transparent",
  },
  thumbSelected: { borderColor: colors.accent },
  thumb: {
    width: THUMB_W - 4,
    height: THUMB_H - 4,
    padding: 6,
    borderRadius: 12,
  },
  thumbLight: { backgroundColor: "#F4F4F0" },
  thumbDark: { backgroundColor: "#0C0C0C" },
  thumbCard: {
    flex: 1,
    borderRadius: 8,
    backgroundColor: "#FFFFFF",
    padding: 7,
    gap: 4,
  },
  thumbCardDark: { backgroundColor: "#1C1C1C" },
  thumbLine: { height: 4, borderRadius: 2, backgroundColor: "#8F918D" },
  thumbDot: {
    position: "absolute",
    right: 8,
    bottom: 7,
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: colors.accent,
  },
  // Dark half of the System thumb: an oversized clip rotated to the diagonal
  // and pushed below it, with the content counter-transformed back into place.
  diagonal: {
    position: "absolute",
    left: -THUMB_W / 2,
    top: -THUMB_H / 2,
    width: THUMB_W * 2,
    height: THUMB_H * 2,
    overflow: "hidden",
    transform: [{ rotate: "-34deg" }, { translateY: THUMB_H }],
  },
  diagonalInner: {
    position: "absolute",
    left: THUMB_W / 2,
    top: THUMB_H / 2,
    transform: [{ translateY: -THUMB_H }, { rotate: "34deg" }],
  },
  modeLabel: { fontFamily: fonts.sans, fontSize: 15, color: colors.ink },
  modeLabelSelected: { color: colors.accent },
  rowDivided: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  root: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 18, paddingTop: 22, gap: 14, paddingBottom: 40 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 6,
  },
  close: { fontSize: 26, lineHeight: 28, color: colors.ink, marginTop: -2 },
  title: { fontFamily: fonts.sansSemi, fontSize: 17, color: colors.ink },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.card,
    paddingHorizontal: 16,
    paddingVertical: 6,
  },
  accountRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    paddingVertical: 12,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.bgDeep,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: {
    fontFamily: fonts.sansBold,
    fontSize: 13,
    color: colors.accent,
  },
  email: { fontFamily: fonts.sansMedium, fontSize: 16, color: colors.ink },
  sub: {
    fontFamily: fonts.sans,
    fontSize: 13,
    color: colors.inkMute,
    marginTop: 2,
  },
  section: {
    fontFamily: fonts.sans,
    fontSize: 14,
    color: colors.inkMute,
    marginTop: 8,
    marginLeft: 6,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 10,
  },
  rowLabel: { fontFamily: fonts.sans, fontSize: 16, color: colors.ink },
  logout: {
    marginTop: 16,
    backgroundColor: colors.surface,
    borderRadius: radius.card,
    paddingVertical: 16,
    alignItems: "center",
  },
  logoutText: {
    fontFamily: fonts.sansSemi,
    fontSize: 16,
    color: colors.danger,
  },
});
