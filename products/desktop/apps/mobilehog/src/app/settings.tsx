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
import { usePrefs } from "@/lib/prefs";
import { colors, fonts, radius } from "@/lib/theme";

export default function SettingsSheet() {
  const router = useRouter();
  const session = useAuth((s) => s.session);
  const logout = useAuth((s) => s.logout);
  const hedgehogMode = usePrefs((s) => s.hedgehogMode);
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
        <View style={styles.row}>
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

const styles = StyleSheet.create({
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
    backgroundColor: "#FFFFFF",
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
    backgroundColor: "#FFFFFF",
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
