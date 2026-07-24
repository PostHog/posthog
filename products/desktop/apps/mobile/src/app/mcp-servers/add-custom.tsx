import { Text } from "@components/text";
import { router } from "expo-router";
import { Lock } from "phosphor-react-native";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { FloatingMcpHeader } from "@/features/mcp/components/FloatingMcpHeader";
import { useMcpInstallations } from "@/features/mcp/hooks";
import { installCustomWithOAuth } from "@/features/mcp/oauth";
import type { McpAuthType } from "@/features/mcp/types";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";

const log = logger.scope("mcp-add-custom");

const AUTH_OPTIONS: { value: McpAuthType; label: string }[] = [
  { value: "none", label: "None" },
  { value: "api_key", label: "API key" },
  { value: "oauth", label: "OAuth" },
];

export default function AddCustomMcpServerScreen() {
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();
  const installations = useMcpInstallations();

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [authType, setAuthType] = useState<McpAuthType>("none");
  const [apiKey, setApiKey] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    setError(null);
    if (!name.trim()) return setError("Name is required");
    if (!url.trim()) return setError("URL is required");

    setSubmitting(true);
    try {
      await installCustomWithOAuth({
        name: name.trim(),
        url: url.trim(),
        auth_type: authType,
        description: description.trim() || undefined,
        api_key:
          authType === "api_key" && apiKey.trim() ? apiKey.trim() : undefined,
        client_id:
          authType === "oauth" && clientId.trim() ? clientId.trim() : undefined,
        client_secret:
          authType === "oauth" && clientSecret.trim()
            ? clientSecret.trim()
            : undefined,
      });
      await installations.refetch();
      router.back();
    } catch (err) {
      log.warn("Custom install failed", err);
      setError(err instanceof Error ? err.message : "Install failed");
      setSubmitting(false);
    }
  };

  return (
    <View className="flex-1 bg-background">
      <FloatingMcpHeader title="Add custom server" />
      <KeyboardAvoidingView
        className="flex-1"
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={insets.top + 60}
      >
        <ScrollView
          className="flex-1"
          contentContainerStyle={{
            paddingTop: insets.top + 60,
            paddingBottom: bottom("default"),
            paddingHorizontal: 16,
          }}
          keyboardShouldPersistTaps="handled"
        >
          <FieldLabel>Name</FieldLabel>
          <FieldInput
            value={name}
            onChangeText={setName}
            placeholder="My server"
            autoCapitalize="none"
            autoCorrect={false}
          />

          <FieldLabel>URL</FieldLabel>
          <FieldInput
            value={url}
            onChangeText={setUrl}
            placeholder="https://example.com/mcp"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />

          <FieldLabel>Description (optional)</FieldLabel>
          <FieldInput
            value={description}
            onChangeText={setDescription}
            placeholder="What does this server do?"
          />

          <FieldLabel>Auth type</FieldLabel>
          <View className="mb-4 flex-row gap-2">
            {AUTH_OPTIONS.map((option) => {
              const active = authType === option.value;
              return (
                <Pressable
                  key={option.value}
                  onPress={() => setAuthType(option.value)}
                  className={`flex-1 items-center rounded-lg border px-3 py-2 ${active ? "border-accent-9 bg-accent-3" : "border-gray-5 bg-card active:bg-gray-2"}`}
                >
                  <Text
                    className={`font-medium text-[13px] ${active ? "text-accent-11" : "text-gray-11"}`}
                  >
                    {option.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          {authType === "api_key" ? (
            <>
              <FieldLabel>API key</FieldLabel>
              <FieldInput
                value={apiKey}
                onChangeText={setApiKey}
                placeholder="Paste your API key"
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
              />
            </>
          ) : null}

          {authType === "oauth" ? (
            <>
              <View className="mb-3 flex-row items-start gap-2 rounded-lg border border-gray-5 bg-card p-3">
                <Lock size={14} color={themeColors.gray[11]} />
                <Text className="flex-1 text-[12px] text-gray-11">
                  You'll be sent to the provider to sign in after submitting.
                </Text>
              </View>
              <FieldLabel>OAuth client ID</FieldLabel>
              <FieldInput
                value={clientId}
                onChangeText={setClientId}
                placeholder="OAuth client ID"
                autoCapitalize="none"
                autoCorrect={false}
              />
              <FieldLabel>OAuth client secret</FieldLabel>
              <FieldInput
                value={clientSecret}
                onChangeText={setClientSecret}
                placeholder="OAuth client secret"
                secureTextEntry
                autoCapitalize="none"
                autoCorrect={false}
              />
            </>
          ) : null}

          {error ? (
            <Text className="mb-3 text-[13px] text-status-error">{error}</Text>
          ) : null}

          <Pressable
            onPress={handleSubmit}
            disabled={submitting}
            className="items-center rounded-lg bg-accent-9 py-3 active:opacity-80"
          >
            {submitting ? (
              <ActivityIndicator color={themeColors.accent.contrast} />
            ) : (
              <Text className="font-semibold text-[15px] text-accent-contrast">
                Install
              </Text>
            )}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

function FieldLabel({ children }: { children: string }) {
  return (
    <Text className="mt-3 mb-1 font-medium text-[13px] text-gray-12">
      {children}
    </Text>
  );
}

function FieldInput(props: React.ComponentProps<typeof TextInput>) {
  const themeColors = useThemeColors();
  return (
    <TextInput
      {...props}
      placeholderTextColor={themeColors.gray[10]}
      className="rounded-lg border border-gray-5 bg-card px-3 py-2.5 text-[14px] text-gray-12"
      style={{ minHeight: 44 }}
    />
  );
}
