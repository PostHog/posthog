import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Glass } from "@/components/Glass";
import { Logomark } from "@/components/Icons";
import { DEV_EMAIL, DEV_PASSWORD } from "@/config";
import { type Region, useAuth } from "@/lib/auth";
import { colors, fonts, radius } from "@/lib/theme";

const REGIONS: Array<{ key: Region; label: string }> = [
  ...(__DEV__ ? [{ key: "local" as const, label: "Local" }] : []),
  { key: "us", label: "US Cloud" },
  { key: "eu", label: "EU Cloud" },
];

export default function LoginScreen() {
  const login = useAuth((s) => s.login);
  const loginWithOAuth = useAuth((s) => s.loginWithOAuth);
  const [region, setRegion] = useState<Region>(__DEV__ ? "local" : "us");
  const [email, setEmail] = useState(__DEV__ ? DEV_EMAIL : "");
  const [password, setPassword] = useState(__DEV__ ? DEV_PASSWORD : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canSubmit = region !== "local" || (!!email && !!password);

  const submit = async (): Promise<void> => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (region === "local") await login(email.trim(), password);
      else await loginWithOAuth(region);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.root}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <View style={styles.hero}>
        <Logomark size={72} />
        <Text style={styles.wordmark}>PostHog</Text>
      </View>
      <Glass style={styles.segment}>
        {REGIONS.map((option) => {
          const active = option.key === region;
          return (
            <Pressable
              key={option.key}
              onPress={() => {
                setRegion(option.key);
                setError(null);
              }}
              style={[styles.segmentItem, active && styles.segmentActive]}
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
      {region === "local" ? (
        <Glass style={styles.card}>
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
          <View style={styles.divider} />
          <TextInput
            value={password}
            onChangeText={setPassword}
            placeholder="Password"
            placeholderTextColor={colors.inkMute}
            secureTextEntry
            textContentType="password"
            onSubmitEditing={submit}
            style={styles.input}
          />
        </Glass>
      ) : null}
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        onPress={submit}
        disabled={busy || !canSubmit}
        style={({ pressed }) => [
          (busy || !canSubmit) && { opacity: 0.4 },
          pressed && { opacity: 0.7 },
        ]}
      >
        <Glass interactive tint="rgba(255,92,28,0.9)" style={styles.button}>
          {busy ? (
            <ActivityIndicator color="#FFFFFF" />
          ) : (
            <Text style={styles.buttonText}>
              {region === "local" ? "Sign in" : "Sign in with PostHog"}
            </Text>
          )}
        </Glass>
      </Pressable>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.bg,
    justifyContent: "center",
    paddingHorizontal: 28,
    gap: 18,
  },
  hero: { alignItems: "center", gap: 6, marginBottom: 14 },
  wordmark: { fontFamily: fonts.serif, fontSize: 36, color: colors.ink },
  card: { borderRadius: radius.card, overflow: "hidden" },
  segment: {
    flexDirection: "row",
    borderRadius: radius.pill,
    padding: 4,
    overflow: "hidden",
  },
  segmentItem: {
    flex: 1,
    paddingVertical: 9,
    borderRadius: radius.pill,
    alignItems: "center",
  },
  segmentActive: { backgroundColor: colors.dark },
  segmentText: {
    fontFamily: fonts.sansMedium,
    fontSize: 14,
    color: colors.inkSoft,
  },
  segmentTextActive: { color: colors.darkText },
  input: {
    fontFamily: fonts.sans,
    fontSize: 17,
    color: colors.ink,
    paddingHorizontal: 18,
    paddingVertical: 16,
  },
  divider: {
    height: StyleSheet.hairlineWidth,
    backgroundColor: colors.line,
    marginHorizontal: 18,
  },
  error: {
    color: colors.danger,
    fontFamily: fonts.sans,
    fontSize: 13,
    lineHeight: 18,
    textAlign: "center",
  },
  button: {
    borderRadius: radius.pill,
    paddingVertical: 16,
    alignItems: "center",
    overflow: "hidden",
  },
  buttonText: {
    color: colors.darkText,
    fontSize: 16,
    fontFamily: fonts.sansSemi,
  },
});
