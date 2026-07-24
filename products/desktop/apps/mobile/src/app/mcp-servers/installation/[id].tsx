import { Text } from "@components/text";
import { router, useLocalSearchParams } from "expo-router";
import {
  ArrowsClockwise,
  CheckCircle,
  Trash,
  Warning,
} from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  Switch,
  View,
} from "react-native";
import { FloatingMcpHeader } from "@/features/mcp/components/FloatingMcpHeader";
import { ServerIcon } from "@/features/mcp/components/ServerIcon";
import {
  useMcpInstallations,
  useMcpInstallationTools,
  useRefreshMcpInstallationTools,
  useUninstallMcpServer,
  useUpdateMcpServerInstallation,
  useUpdateMcpToolApproval,
} from "@/features/mcp/hooks";
import { reauthorizeInstallation } from "@/features/mcp/oauth";
import { getMcpConnectionManager } from "@/features/mcp/service";
import type { McpApprovalState } from "@/features/mcp/types";
import { isStdioServer } from "@/features/mcp/types";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";

const log = logger.scope("mcp-installation-detail");

export default function McpInstallationDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();

  const installations = useMcpInstallations();
  const installation = useMemo(
    () => installations.data?.find((i) => i.id === id) ?? null,
    [installations.data, id],
  );

  const tools = useMcpInstallationTools(installation?.id ?? null);
  const refreshMutation = useRefreshMcpInstallationTools();
  const uninstallMutation = useUninstallMcpServer();
  const updateMutation = useUpdateMcpServerInstallation();
  const approvalMutation = useUpdateMcpToolApproval();

  const [reauthLoading, setReauthLoading] = useState(false);

  if (installations.isPending || !installation) {
    return (
      <View className="flex-1 bg-background">
        <FloatingMcpHeader title="Server" />
        <View
          className="flex-1 items-center justify-center"
          style={{ paddingTop: insets.top + 60 }}
        >
          {installations.isPending ? (
            <ActivityIndicator color={themeColors.accent[9]} />
          ) : (
            <Text className="text-[14px] text-gray-11">
              Installation not found.
            </Text>
          )}
        </View>
      </View>
    );
  }

  const stdio = isStdioServer(installation);

  const handleEnabledChange = (enabled: boolean) => {
    updateMutation.mutate({
      installationId: installation.id,
      updates: { is_enabled: enabled },
    });
  };

  const handleReauthorize = async () => {
    setReauthLoading(true);
    try {
      await reauthorizeInstallation(installation.id);
      await installations.refetch();
    } catch (err) {
      log.warn("Reauth failed", err);
    } finally {
      setReauthLoading(false);
    }
  };

  const handleUninstall = () => {
    Alert.alert(
      "Uninstall server",
      `Remove "${installation.display_name || installation.name}"? Any task using its tools will lose access.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Uninstall",
          style: "destructive",
          onPress: async () => {
            try {
              await uninstallMutation.mutateAsync(installation.id);
              await getMcpConnectionManager().close(installation.id);
              await installations.refetch();
              router.back();
            } catch (err) {
              log.warn("Uninstall failed", err);
              Alert.alert(
                "Failed to uninstall",
                err instanceof Error ? err.message : "Unknown error",
              );
            }
          },
        },
      ],
    );
  };

  const handleApprovalChange = (toolName: string, state: McpApprovalState) => {
    approvalMutation.mutate({
      installationId: installation.id,
      toolName,
      approval_state: state,
    });
  };

  return (
    <View className="flex-1 bg-background">
      <FloatingMcpHeader
        title={installation.display_name || installation.name}
      />

      <ScrollView
        className="flex-1"
        contentContainerStyle={{
          paddingTop: insets.top + 60,
          paddingBottom: bottom("default"),
          paddingHorizontal: 16,
        }}
        refreshControl={
          <RefreshControl
            refreshing={installations.isRefetching || tools.isRefetching}
            onRefresh={() => {
              installations.refetch();
              tools.refetch();
            }}
            tintColor={themeColors.accent[9]}
          />
        }
      >
        {/* Header */}
        <View className="mb-4 flex-row items-center gap-3">
          <ServerIcon
            iconDomain={installation.icon_domain}
            serverUrl={installation.url}
            size={48}
          />
          <View className="min-w-0 flex-1">
            <Text className="font-semibold text-[18px] text-gray-12">
              {installation.display_name || installation.name}
            </Text>
            {installation.description ? (
              <Text
                className="mt-0.5 text-[12px] text-gray-10"
                numberOfLines={2}
              >
                {installation.description}
              </Text>
            ) : null}
          </View>
        </View>

        {/* Status pills */}
        <View className="mb-4 flex-row flex-wrap gap-2">
          <View className="rounded bg-gray-3 px-2 py-0.5">
            <Text className="font-medium text-[11px] text-gray-11 uppercase">
              {installation.auth_type === "oauth"
                ? "OAuth"
                : installation.auth_type === "api_key"
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
          {installation.needs_reauth ? (
            <View className="flex-row items-center gap-1 rounded bg-card px-2 py-0.5">
              <Warning size={12} color={themeColors.status.warning} />
              <Text className="font-medium text-[11px] text-status-warning uppercase">
                Needs reauth
              </Text>
            </View>
          ) : null}
        </View>

        {/* Enabled toggle */}
        <View className="mb-4 flex-row items-center justify-between rounded-lg border border-gray-5 bg-card px-4 py-3">
          <View className="flex-1">
            <Text className="font-medium text-[15px] text-gray-12">
              Enabled
            </Text>
            <Text className="text-[12px] text-gray-10">
              Allow your agent to call this server's tools
            </Text>
          </View>
          <Switch
            value={installation.is_enabled ?? true}
            onValueChange={handleEnabledChange}
          />
        </View>

        {/* Reauth */}
        {installation.needs_reauth ? (
          <Pressable
            onPress={handleReauthorize}
            disabled={reauthLoading}
            className="mb-4 flex-row items-center justify-center gap-2 rounded-lg bg-accent-9 py-3 active:opacity-80"
          >
            {reauthLoading ? (
              <ActivityIndicator color={themeColors.accent.contrast} />
            ) : (
              <Text className="font-semibold text-[14px] text-accent-contrast">
                Reauthorize
              </Text>
            )}
          </Pressable>
        ) : null}

        {/* Tools */}
        <View className="mb-3 flex-row items-center justify-between">
          <Text className="font-semibold text-[14px] text-gray-12">
            Tools ({installation.tool_count})
          </Text>
          <Pressable
            onPress={() => refreshMutation.mutate(installation.id)}
            disabled={refreshMutation.isPending}
            hitSlop={8}
            className="flex-row items-center gap-1 rounded-md bg-gray-3 px-2 py-1 active:opacity-60"
          >
            <ArrowsClockwise
              size={12}
              color={themeColors.gray[12]}
              weight="bold"
            />
            <Text className="font-medium text-[12px] text-gray-12">
              Refresh
            </Text>
          </Pressable>
        </View>

        {tools.isPending ? (
          <View className="rounded-lg border border-gray-5 bg-card p-4">
            <ActivityIndicator color={themeColors.accent[9]} />
          </View>
        ) : tools.data?.length ? (
          <View className="overflow-hidden rounded-lg border border-gray-5 bg-card">
            {tools.data.map((tool, idx) => {
              const last = idx === (tools.data?.length ?? 0) - 1;
              const isApproved = tool.approval_state === "approved";
              return (
                <View
                  key={tool.id}
                  className={`px-4 py-3 ${last ? "" : "border-gray-5 border-b"}`}
                >
                  <View className="flex-row items-center justify-between">
                    <View className="min-w-0 flex-1 pr-3">
                      <Text
                        className="font-medium text-[14px] text-gray-12"
                        numberOfLines={1}
                      >
                        {tool.display_name || tool.tool_name}
                      </Text>
                      {tool.description ? (
                        <Text
                          className="mt-0.5 text-[12px] text-gray-10 leading-snug"
                          numberOfLines={2}
                        >
                          {tool.description}
                        </Text>
                      ) : null}
                    </View>
                    <Pressable
                      onPress={() =>
                        handleApprovalChange(
                          tool.tool_name,
                          isApproved ? "needs_approval" : "approved",
                        )
                      }
                      hitSlop={6}
                      className="flex-row items-center gap-1"
                    >
                      {isApproved ? (
                        <>
                          <CheckCircle
                            size={14}
                            color={themeColors.status.success}
                            weight="fill"
                          />
                          <Text className="font-medium text-[12px] text-status-success">
                            Approved
                          </Text>
                        </>
                      ) : (
                        <View className="rounded bg-gray-3 px-2 py-1">
                          <Text className="font-medium text-[11px] text-gray-11 uppercase">
                            Approve
                          </Text>
                        </View>
                      )}
                    </Pressable>
                  </View>
                </View>
              );
            })}
          </View>
        ) : (
          <View className="rounded-lg border border-gray-5 bg-card p-4">
            <Text className="text-[13px] text-gray-10">
              No tools discovered yet. Tap Refresh to retry.
            </Text>
          </View>
        )}

        {/* Uninstall */}
        <Pressable
          onPress={handleUninstall}
          disabled={uninstallMutation.isPending}
          className="mt-6 flex-row items-center justify-center gap-2 rounded-lg border border-status-error bg-card py-3 active:opacity-60"
        >
          <Trash size={14} color={themeColors.status.error} weight="bold" />
          <Text className="font-semibold text-[14px] text-status-error">
            Uninstall server
          </Text>
        </Pressable>
      </ScrollView>
    </View>
  );
}
