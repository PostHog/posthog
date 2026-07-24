import { Text } from "@components/text";
import * as WebBrowser from "expo-web-browser";
import { Pressable, View } from "react-native";
import { useAuthStore } from "@/features/auth";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";
import { startGithubUserIntegrationConnect } from "../api";

const log = logger.scope("github-connection-prompt");

interface GitHubConnectionPromptProps {
  onConnected?: () => void;
  mode?: "card" | "empty";
  title?: string;
  description?: string;
  /**
   * Which GitHub integration to create:
   * - `"user"` (default): the per-user flow (matches desktop) for interactive
   *   task creation — detected via `/api/users/@me/integrations/`.
   * - `"team"`: the environment-level flow for automations, which run
   *   server-side and need a team integration.
   */
  scope?: "user" | "team";
}

export function GitHubConnectionPrompt({
  onConnected,
  mode = "card",
  title = "Connect GitHub to continue",
  description = "You need to connect your GitHub account before using this workflow.",
  scope = "user",
}: GitHubConnectionPromptProps) {
  const { cloudRegion, projectId, getCloudUrlFromRegion } = useAuthStore();
  const themeColors = useThemeColors();

  const handleConnectGitHub = async () => {
    if (!cloudRegion || !projectId) {
      return;
    }

    let authorizeUrl: string;
    if (scope === "user") {
      // Per-user flow (like desktop): the backend picks the right GitHub flow
      // and, because we pass `connect_from: "posthog_mobile"`, redirects the
      // callback to `posthog://github/callback` so this in-app browser closes.
      try {
        const { install_url } = await startGithubUserIntegrationConnect();
        authorizeUrl = install_url;
      } catch (error) {
        log.error("Failed to start GitHub connection", { error });
        return;
      }
    } else {
      // Team/environment flow for automations: creates an environment-scoped
      // integration that `useIntegrations` detects.
      const baseUrl = getCloudUrlFromRegion(cloudRegion);
      authorizeUrl = `${baseUrl}/api/environments/${projectId}/integrations/authorize/?kind=github`;
    }

    const result = await WebBrowser.openAuthSessionAsync(
      authorizeUrl,
      "posthog://github/callback",
    );

    if (
      result.type === "dismiss" ||
      result.type === "cancel" ||
      result.type === "success"
    ) {
      onConnected?.();
    }
  };

  if (mode === "empty") {
    return (
      <View className="flex-1 items-center justify-center p-6">
        <View className="mb-6 h-16 w-16 items-center justify-center rounded-full bg-gray-3">
          <Text className="text-3xl">🔗</Text>
        </View>
        <Text className="mb-2 text-center font-semibold text-gray-12 text-lg">
          Connect GitHub
        </Text>
        <Text className="mb-6 text-center text-gray-11 text-sm">
          Let PostHog work on your repositories.
        </Text>
        <Pressable
          onPress={handleConnectGitHub}
          className="rounded-lg px-6 py-3"
          style={{ backgroundColor: themeColors.accent[9] }}
        >
          <Text className="font-semibold text-accent-contrast">
            Connect GitHub
          </Text>
        </Pressable>
      </View>
    );
  }

  return (
    <View className="mb-4 rounded-lg border border-gray-6 p-4">
      <View className="mb-3 flex-row items-center">
        <Text className="mr-2 text-xl">🔗</Text>
        <Text className="font-semibold text-gray-12">{title}</Text>
      </View>
      <Text className="mb-4 text-gray-11 text-sm">{description}</Text>
      <Pressable
        onPress={handleConnectGitHub}
        className="items-center rounded-lg py-3"
        style={{ backgroundColor: themeColors.accent[9] }}
      >
        <Text className="font-semibold text-accent-contrast">
          Connect GitHub
        </Text>
      </Pressable>
    </View>
  );
}
