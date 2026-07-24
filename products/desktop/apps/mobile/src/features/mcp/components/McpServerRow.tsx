import { Text } from "@components/text";
import { CaretRight, Lock, Warning } from "phosphor-react-native";
import type { ReactNode } from "react";
import { Pressable, View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import type { McpRecommendedServer, McpServerInstallation } from "../types";
import { isStdioServer } from "../types";
import { ServerIcon } from "./ServerIcon";

interface McpServerRowProps {
  title: string;
  subtitle?: string;
  description?: string;
  authType?: "api_key" | "oauth" | "none";
  badge?: ReactNode;
  isStdio?: boolean;
  needsReauth?: boolean;
  installed?: boolean;
  iconDomain?: string | null;
  serverUrl?: string | null;
  onPress: () => void;
}

function authBadge(auth?: "api_key" | "oauth" | "none") {
  if (auth === "oauth") return "OAuth";
  if (auth === "api_key") return "API key";
  return null;
}

export function McpServerRow({
  title,
  subtitle,
  description,
  authType,
  badge,
  isStdio,
  needsReauth,
  installed,
  iconDomain,
  serverUrl,
  onPress,
}: McpServerRowProps) {
  const themeColors = useThemeColors();
  const auth = authBadge(authType);

  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center gap-3 border-gray-5 border-b bg-card px-4 py-3 active:bg-gray-2"
    >
      <ServerIcon iconDomain={iconDomain} serverUrl={serverUrl} size={36} />
      <View className="min-w-0 flex-1">
        <View className="flex-row items-center gap-2">
          <Text
            className="font-semibold text-[15px] text-gray-12"
            numberOfLines={1}
          >
            {title}
          </Text>
          {installed ? (
            <View className="rounded bg-accent-3 px-1.5 py-0.5">
              <Text className="font-medium text-[10px] text-accent-11 uppercase">
                Installed
              </Text>
            </View>
          ) : null}
          {isStdio ? (
            <View className="rounded bg-gray-3 px-1.5 py-0.5">
              <Text className="font-medium text-[10px] text-gray-11 uppercase">
                Desktop only
              </Text>
            </View>
          ) : null}
          {needsReauth ? (
            <View className="flex-row items-center gap-1 rounded bg-card px-1.5 py-0.5">
              <Warning size={10} color={themeColors.status.warning} />
              <Text className="font-medium text-[10px] text-status-warning uppercase">
                Reauth
              </Text>
            </View>
          ) : null}
          {badge}
        </View>
        {subtitle ? (
          <Text className="mt-0.5 text-[12px] text-gray-10" numberOfLines={1}>
            {subtitle}
          </Text>
        ) : null}
        {description ? (
          <Text
            className="mt-0.5 text-[12px] text-gray-11 leading-snug"
            numberOfLines={2}
          >
            {description}
          </Text>
        ) : null}
      </View>
      <View className="flex-row items-center gap-1">
        {auth ? (
          <View className="flex-row items-center gap-1 rounded bg-gray-3 px-1.5 py-0.5">
            {authType === "oauth" ? (
              <Lock size={10} color={themeColors.gray[11]} />
            ) : null}
            <Text className="font-medium text-[10px] text-gray-11 uppercase">
              {auth}
            </Text>
          </View>
        ) : null}
        <CaretRight size={14} color={themeColors.gray[10]} />
      </View>
    </Pressable>
  );
}

export function recommendedToRowProps(
  template: McpRecommendedServer,
  installedNames: Set<string>,
  onPress: (template: McpRecommendedServer) => void,
): McpServerRowProps {
  return {
    title: template.name,
    description: template.description,
    authType: template.auth_type,
    isStdio: isStdioServer(template),
    installed: installedNames.has(template.name),
    iconDomain: template.icon_domain,
    serverUrl: template.url,
    onPress: () => onPress(template),
  };
}

export function installationToRowProps(
  installation: McpServerInstallation,
  onPress: (installation: McpServerInstallation) => void,
): McpServerRowProps {
  return {
    title: installation.display_name || installation.name,
    subtitle: installation.url,
    authType: installation.auth_type,
    isStdio: isStdioServer(installation),
    needsReauth: installation.needs_reauth,
    installed: true,
    iconDomain: installation.icon_domain,
    serverUrl: installation.url,
    onPress: () => onPress(installation),
  };
}
