import { Text } from "@components/text";
import { EXTERNAL_LINKS } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useQueryClient } from "@tanstack/react-query";
import { router } from "expo-router";
import { usePostHog } from "posthog-react-native";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuthStore, useUserQuery } from "@/features/auth";
import { ConsentError } from "@/features/consent/components/ConsentError";
import { ConsentPanel } from "@/features/consent/components/ConsentPanel";
import {
  desktopBetaTermsKeys,
  useOrgConsent,
} from "@/features/consent/hooks/useOrgConsent";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { useThemeColors } from "@/lib/theme";

const ORGANIZATION_ADMIN_LEVEL = 8;

export default function ConsentScreen() {
  const themeColors = useThemeColors();
  const consent = useOrgConsent();
  const { data: user } = useUserQuery();
  const logout = useAuthStore((s) => s.logout);
  const posthog = usePostHog();
  const queryClient = useQueryClient();

  const organization = user?.organization;
  const isAdmin =
    (organization?.membership_level ?? 0) >= ORGANIZATION_ADMIN_LEVEL;

  const acceptAi = async (): Promise<void> => {
    if (!organization) return;
    await getPostHogApiClient().approveAiDataProcessing(organization.id);
    posthog?.capture(ANALYTICS_EVENTS.AI_CONSENT_GRANTED_INAPP);
    await queryClient.invalidateQueries({ queryKey: ["user"] });
  };

  const acceptBeta = async (): Promise<void> => {
    if (!organization) return;
    await getPostHogApiClient().acceptDesktopBetaTerms(organization.id);
    posthog?.capture(ANALYTICS_EVENTS.DESKTOP_BETA_TERMS_ACCEPTED_INAPP);
    await queryClient.invalidateQueries({
      queryKey: desktopBetaTermsKeys.all(),
    });
  };

  const handleLogout = async (): Promise<void> => {
    await logout();
    router.replace("/auth");
  };

  return (
    <SafeAreaView className="flex-1 bg-gray-1">
      <ScrollView
        className="flex-1"
        contentContainerClassName="px-6 pt-12 pb-8"
        keyboardShouldPersistTaps="handled"
      >
        {consent.status === "error" ? (
          <ConsentError onRetry={consent.retry} />
        ) : consent.status === "resolved" && !consent.satisfied ? (
          <ConsentPanel
            organizationName={organization?.name}
            needsAiConsent={consent.needsAiConsent}
            needsBetaTerms={consent.needsBetaTerms}
            isAdmin={isAdmin}
            onAcceptAi={acceptAi}
            onAcceptBeta={acceptBeta}
          />
        ) : (
          <View className="items-center py-24">
            <ActivityIndicator size="large" color={themeColors.accent[9]} />
          </View>
        )}
      </ScrollView>
      <View className="flex-row items-center justify-between px-6 pb-4">
        <Pressable onPress={() => openExternalUrl(EXTERNAL_LINKS.discord)}>
          <Text className="text-gray-11 text-sm">Get support</Text>
        </Pressable>
        <Pressable onPress={handleLogout}>
          <Text className="text-gray-11 text-sm">Log out</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}
