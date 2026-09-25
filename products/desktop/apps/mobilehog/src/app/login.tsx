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
import { DEV_EMAIL, DEV_PASSWORD, POSTHOG_HOST } from "@/config";
import { useAuth } from "@/lib/auth";
import { colors, fonts, radius } from "@/lib/theme";

export default function LoginScreen() {
  const login = useAuth((s) => s.login);
  const [email, setEmail] = useState(__DEV__ ? DEV_EMAIL : "");
  const [password, setPassword] = useState(__DEV__ ? DEV_PASSWORD : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
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
      <View style={styles.blobA} />
      <View style={styles.blobB} />
      <View style={styles.hero}>
        <Logomark size={72} />
        <Text style={styles.wordmark}>PostHog</Text>
        <Text style={styles.tagline}>
          {POSTHOG_HOST.replace(/^https?:\/\//, "")}
        </Text>
      </View>
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
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Pressable
        onPress={submit}
        disabled={busy || !email || !password}
        style={({ pressed }) => [
          styles.button,
          (busy || !email || !password) && { opacity: 0.4 },
          pressed && { opacity: 0.7 },
        ]}
      >
        {busy ? (
          <ActivityIndicator color={colors.darkText} />
        ) : (
          <Text style={styles.buttonText}>Sign in</Text>
        )}
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
  blobA: {
    position: "absolute",
    top: -120,
    right: -80,
    width: 320,
    height: 320,
    borderRadius: 160,
    backgroundColor: "rgba(217,117,91,0.16)",
  },
  blobB: {
    position: "absolute",
    bottom: -140,
    left: -100,
    width: 360,
    height: 360,
    borderRadius: 180,
    backgroundColor: "rgba(28,27,24,0.05)",
  },
  hero: { alignItems: "center", gap: 6, marginBottom: 14 },
  wordmark: { fontFamily: fonts.serif, fontSize: 36, color: colors.ink },
  tagline: { fontFamily: fonts.mono, fontSize: 12, color: colors.inkMute },
  card: { borderRadius: radius.card, overflow: "hidden" },
  input: {
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
    fontSize: 13,
    lineHeight: 18,
    textAlign: "center",
  },
  button: {
    backgroundColor: colors.dark,
    borderRadius: radius.pill,
    paddingVertical: 16,
    alignItems: "center",
  },
  buttonText: { color: colors.darkText, fontSize: 16, fontWeight: "600" },
});
