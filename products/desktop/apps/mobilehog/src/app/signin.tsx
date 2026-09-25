import { useRouter } from "expo-router";
import * as WebBrowser from "expo-web-browser";
import { useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Glass, GlassCircleButton } from "@/components/Glass";
import { DEV_EMAIL, DEV_PASSWORD } from "@/config";
import { type Region, useAuth } from "@/lib/auth";
import { colors, fonts, radius } from "@/lib/theme";

const REGIONS: Array<{ key: Region; label: string }> = [
  { key: "us", label: "🇺🇸 United States" },
  { key: "eu", label: "🇪🇺 European Union" },
  ...(__DEV__ ? [{ key: "local" as const, label: "Local" }] : []),
];

const REGION_DOCS = "https://posthog.com/docs/getting-started/cloud";

// Region, then one button. PostHog's own login page handles passwords, Google,
// GitHub, GitLab and SSO inside the OAuth sheet, so none of that lives here.
export default function SignInSheet() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const login = useAuth((s) => s.login);
  const loginWithOAuth = useAuth((s) => s.loginWithOAuth);
  const [region, setRegion] = useState<Region>(__DEV__ ? "local" : "us");
  const [email, setEmail] = useState(__DEV__ ? DEV_EMAIL : "");
  const [password, setPassword] = useState(__DEV__ ? DEV_PASSWORD : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const local = region === "local";

  const submit = async (signup = false): Promise<void> => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (region === "local") await login(email.trim(), password);
      else await loginWithOAuth(region, signup);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <ScrollView
      style={styles.root}
      contentContainerStyle={[
        styles.content,
        { paddingBottom: insets.bottom + 24 },
      ]}
      keyboardShouldPersistTaps="handled"
    >
      <View style={styles.header}>
        <GlassCircleButton size={44} onPress={() => router.back()}>
          <Text style={styles.close}>×</Text>
        </GlassCircleButton>
        <Text style={styles.headerTitle}>Sign in</Text>
        <View style={{ width: 44 }} />
      </View>

      <Text style={styles.title}>Welcome back.</Text>
      <Text style={styles.subtitle}>Let's go ship something.</Text>

      <View style={styles.labelRow}>
        <Text style={styles.label}>Data region</Text>
        <Pressable onPress={() => WebBrowser.openBrowserAsync(REGION_DOCS)}>
          <Text style={styles.link}>What is this?</Text>
        </Pressable>
      </View>
      <View style={styles.card}>
        {REGIONS.map((option, i) => {
          const active = option.key === region;
          return (
            <Pressable
              key={option.key}
              onPress={() => {
                setRegion(option.key);
                setError(null);
              }}
              style={[styles.row, i > 0 && styles.rowDivided]}
            >
              <Text style={styles.rowLabel}>{option.label}</Text>
              <View style={[styles.radio, active && styles.radioOn]}>
                {active ? <View style={styles.radioDot} /> : null}
              </View>
            </Pressable>
          );
        })}
      </View>

      {local ? (
        <View style={styles.card}>
          <TextInput
            value={email}
            onChangeText={setEmail}
            placeholder="Email"
            placeholderTextColor={colors.inkMute}
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="email-address"
            textContentType="username"
            style={styles.input}
          />
          <TextInput
            value={password}
            onChangeText={setPassword}
            placeholder="Password"
            placeholderTextColor={colors.inkMute}
            secureTextEntry
            textContentType="password"
            onSubmitEditing={() => submit()}
            style={[styles.input, styles.rowDivided]}
          />
        </View>
      ) : null}

      {error ? <Text style={styles.error}>{error}</Text> : null}

      <Pressable
        onPress={() => submit()}
        disabled={busy || (local && !(email && password))}
        style={({ pressed }) => [
          styles.primary,
          (busy || (local && !(email && password))) && { opacity: 0.4 },
          pressed && { opacity: 0.7 },
        ]}
      >
        <Glass interactive tint="rgba(255,92,28,0.9)" style={styles.button}>
          {busy ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text style={styles.buttonText}>
              {local ? "Sign in" : "Continue with PostHog"}
            </Text>
          )}
        </Glass>
      </Pressable>
      {!local ? (
        <Text style={styles.hint}>
          Password, Google, GitHub, GitLab and SSO all work on the next screen.
        </Text>
      ) : null}

      {!local ? (
        <Pressable
          onPress={() => submit(true)}
          disabled={busy}
          style={styles.signup}
        >
          <Text style={styles.signupText}>
            New to PostHog? <Text style={styles.link}>Create an account</Text>
          </Text>
        </Pressable>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  content: { padding: 18, paddingTop: 22, gap: 12 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 10,
  },
  close: { fontSize: 26, lineHeight: 28, color: colors.ink, marginTop: -2 },
  headerTitle: { fontFamily: fonts.sansSemi, fontSize: 17, color: colors.ink },
  title: {
    fontFamily: fonts.sansBold,
    fontSize: 30,
    color: colors.ink,
    marginLeft: 6,
  },
  subtitle: {
    fontFamily: fonts.sans,
    fontSize: 17,
    color: colors.inkSoft,
    marginLeft: 6,
    marginTop: -8,
    marginBottom: 14,
  },
  labelRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    marginHorizontal: 6,
  },
  label: { fontFamily: fonts.sansMedium, fontSize: 14, color: colors.inkSoft },
  link: { fontFamily: fonts.sansMedium, fontSize: 14, color: colors.accent },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.card,
    paddingHorizontal: 16,
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 14,
  },
  rowDivided: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  rowLabel: { fontFamily: fonts.sans, fontSize: 16, color: colors.ink },
  radio: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 2,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
  },
  radioOn: { borderColor: colors.accent },
  radioDot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: colors.accent,
  },
  input: {
    fontFamily: fonts.sans,
    fontSize: 16,
    color: colors.ink,
    paddingVertical: 14,
  },
  error: {
    color: colors.danger,
    fontFamily: fonts.sans,
    fontSize: 13,
    lineHeight: 18,
    marginHorizontal: 6,
  },
  primary: { marginTop: 10 },
  button: {
    borderRadius: radius.pill,
    paddingVertical: 16,
    alignItems: "center",
    overflow: "hidden",
  },
  buttonText: { color: "#FFFFFF", fontSize: 16, fontFamily: fonts.sansSemi },
  hint: {
    fontFamily: fonts.sans,
    fontSize: 13,
    lineHeight: 18,
    color: colors.inkMute,
    textAlign: "center",
    marginHorizontal: 12,
  },
  signup: { alignItems: "center", marginTop: 18 },
  signupText: { fontFamily: fonts.sans, fontSize: 15, color: colors.inkSoft },
});
