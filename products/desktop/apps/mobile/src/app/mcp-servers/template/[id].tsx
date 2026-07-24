import { Text } from "@components/text";
import { router, useLocalSearchParams } from "expo-router";
import { Lock, Warning } from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  TextInput,
  View,
} from "react-native";
import { FloatingMcpHeader } from "@/features/mcp/components/FloatingMcpHeader";
import { ServerIcon } from "@/features/mcp/components/ServerIcon";
import {
  useInstallMcpTemplate,
  useMcpInstallations,
  useMcpMarketplace,
} from "@/features/mcp/hooks";
import { installTemplateWithOAuth } from "@/features/mcp/oauth";
import { isStdioServer } from "@/features/mcp/types";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { logger } from "@/lib/logger";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { useThemeColors } from "@/lib/theme";

const log = logger.scope("mcp-template-detail");

export default function McpTemplateDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();

  const marketplace = useMcpMarketplace();
  const installations = useMcpInstallations();
  const template = useMemo(
    () => marketplace.data?.find((t) => t.id === id) ?? null,
    [marketplace.data, id],
  );
  const installed = useMemo(
    () =>
      template
        ? (installations.data ?? []).some((i) => i.name === template.name)
        : false,
    [installations.data, template],
  );

  const [apiKey, setApiKey] = useState("");
  const [installing, setInstalling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const installMutation = useInstallMcpTemplate();

  if (marketplace.isPending) {
    return (
      <Loading topInset={insets.top + 60} themeColor={themeColors.accent[9]} />
    );
  }

  if (!template) {
    return (
      <View className="flex-1 bg-background">
        <FloatingMcpHeader title="Server" />
        <View
          className="flex-1 items-center justify-center px-8"
          style={{ paddingTop: insets.top + 60 }}
        >
          <Text className="text-center text-[14px] text-gray-11">
            Template not found.
          </Text>
        </View>
      </View>
    );
  }

  const stdio = isStdioServer(template);

  const handleInstall = async () => {
    if (!template) return;
    setError(null);
    setInstalling(true);
    try {
      if (template.auth_type === "oauth") {
        const result = await installTemplateWithOAuth({
          template_id: template.id,
        });
        if (result === "cancelled") {
          setInstalling(false);
          return;
        }
      } else if (template.auth_type === "api_key") {
        if (!apiKey.trim()) {
          setError("API key is required");
          setInstalling(false);
          return;
        }
        await installMutation.mutateAsync({
          template_id: template.id,
          api_key: apiKey.trim(),
        });
      } else {
        await installMutation.mutateAsync({ template_id: template.id });
      }
      // Refresh and pop back to the list.
      await installations.refetch();
      router.back();
    } catch (err) {
      log.warn("Install failed", err);
      setError(err instanceof Error ? err.message : "Install failed");
      setInstalling(false);
    }
  };

  return (
    <View className="flex-1 bg-background">
      <FloatingMcpHeader title={template.name} />
      <ScrollView
        className="flex-1"
        contentContainerStyle={{
          paddingTop: insets.top + 60,
          paddingBottom: bottom("default"),
          paddingHorizontal: 16,
        }}
      >
        <View className="mb-4 flex-row items-center gap-3">
          <ServerIcon
            iconDomain={template.icon_domain}
            serverUrl={template.url}
            size={48}
          />
          <View className="min-w-0 flex-1">
            <Text className="font-semibold text-[18px] text-gray-12">
              {template.name}
            </Text>
            {template.category ? (
              <Text className="text-[12px] text-gray-10">
                {template.category}
              </Text>
            ) : null}
          </View>
        </View>

        {template.description ? (
          <Text className="mb-4 text-[14px] text-gray-11 leading-snug">
            {template.description}
          </Text>
        ) : null}

        <View className="mb-4 gap-2">
          <View className="flex-row items-center gap-2">
            <View className="rounded bg-gray-3 px-2 py-0.5">
              <Text className="font-medium text-[11px] text-gray-11 uppercase">
                {template.auth_type === "oauth"
                  ? "OAuth"
                  : template.auth_type === "api_key"
                    ? "API key"
                    : "No auth"}
              </Text>
            </View>
            {stdio ? (
              <View className="rounded bg-gray-3 px-2 py-0.5">
                <Text className="font-medium text-[11px] text-gray-11 uppercase">
                  Desktop only
                </Text>
              </View>
            ) : null}
          </View>
          {template.url ? (
            <Text className="text-[12px] text-gray-10" numberOfLines={2}>
              {template.url}
            </Text>
          ) : null}
        </View>

        {template.docs_url ? (
          <Pressable
            onPress={() => openExternalUrl(template.docs_url as string)}
            className="mb-4 rounded-lg border border-gray-5 bg-card px-3 py-2 active:bg-gray-2"
          >
            <Text className="font-medium text-[13px] text-accent-11">
              View docs ↗
            </Text>
          </Pressable>
        ) : null}

        {stdio ? (
          <View className="mb-4 flex-row items-start gap-2 rounded-lg border border-gray-5 bg-card p-3">
            <Warning size={16} color={themeColors.status.warning} />
            <Text className="flex-1 text-[13px] text-gray-12">
              This server uses stdio and can't run on mobile. Install it from
              the desktop client to use it on this device.
            </Text>
          </View>
        ) : null}

        {template.auth_type === "api_key" && !stdio ? (
          <View className="mb-4">
            <Text className="mb-1 font-medium text-[13px] text-gray-12">
              API key
            </Text>
            <TextInput
              value={apiKey}
              onChangeText={setApiKey}
              placeholder="Paste your API key"
              placeholderTextColor={themeColors.gray[10]}
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry
              className="rounded-lg border border-gray-5 bg-card px-3 py-2.5 text-[14px] text-gray-12"
            />
          </View>
        ) : null}

        {template.auth_type === "oauth" && !stdio ? (
          <View className="mb-4 flex-row items-start gap-2 rounded-lg border border-gray-5 bg-card p-3">
            <Lock size={14} color={themeColors.gray[11]} />
            <Text className="flex-1 text-[13px] text-gray-11">
              You'll be sent to the provider to sign in, then bounced back to
              the app once you authorize.
            </Text>
          </View>
        ) : null}

        {error ? (
          <Text className="mb-3 text-[13px] text-status-error">{error}</Text>
        ) : null}

        <Pressable
          onPress={handleInstall}
          disabled={installing || installed || stdio}
          className={`items-center rounded-lg py-3 ${stdio || installed ? "bg-gray-3 opacity-60" : "bg-accent-9 active:opacity-80"}`}
        >
          {installing ? (
            <ActivityIndicator color={themeColors.accent.contrast} />
          ) : (
            <Text
              className={`font-semibold text-[15px] ${stdio || installed ? "text-gray-11" : "text-accent-contrast"}`}
            >
              {installed ? "Already installed" : "Install"}
            </Text>
          )}
        </Pressable>
      </ScrollView>
    </View>
  );
}

function Loading({
  topInset,
  themeColor,
}: {
  topInset: number;
  themeColor: string;
}) {
  return (
    <View className="flex-1 bg-background">
      <FloatingMcpHeader title="Server" />
      <View
        className="flex-1 items-center justify-center"
        style={{ paddingTop: topInset }}
      >
        <ActivityIndicator color={themeColor} />
      </View>
    </View>
  );
}
