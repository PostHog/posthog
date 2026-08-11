import { router, useLocalSearchParams } from "expo-router";
import { useCallback, useMemo, useState } from "react";
import {
  ActivityIndicator,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { QrScanModal, type QrScanResult } from "@/components/QrScanModal";
import { type CloudRegion, useAuthStore } from "@/features/auth";
import {
  ANALYTICS_EVENTS,
  type SignInFailureReason,
  type SignInMethod,
  useAnalytics,
} from "@/lib/analytics";
import { useThemeColors } from "@/lib/theme";

type RegionOption = { value: CloudRegion; label: string };

const PRODUCTION_REGIONS: RegionOption[] = [
  { value: "us", label: "US Cloud" },
  { value: "eu", label: "EU Cloud" },
];

const DEV_REGIONS: RegionOption[] = [
  ...PRODUCTION_REGIONS,
  { value: "dev", label: "Development" },
];

export default function AuthScreen() {
  const themeColors = useThemeColors();
  const { next } = useLocalSearchParams<{ next?: string }>();

  // Only show dev region in development builds
  const regions = useMemo<RegionOption[]>(
    () => (__DEV__ ? DEV_REGIONS : PRODUCTION_REGIONS),
    [],
  );
  const [selectedRegion, setSelectedRegion] = useState<CloudRegion>("us");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [devToken, setDevToken] = useState("");
  const [devProjectId, setDevProjectId] = useState("");
  const [scannerVisible, setScannerVisible] = useState(false);

  const { loginWithOAuth, loginWithPersonalApiKey } = useAuthStore();
  const analytics = useAnalytics();

  const trackSignInStarted = (method: SignInMethod) => {
    analytics.track(ANALYTICS_EVENTS.SIGN_IN_STARTED, {
      method,
      region: selectedRegion,
    });
  };

  const trackSignInCompleted = (method: SignInMethod) => {
    analytics.track(ANALYTICS_EVENTS.SIGN_IN_COMPLETED, {
      method,
      region: selectedRegion,
    });
  };

  const trackSignInFailed = (method: SignInMethod, message: string) => {
    const reason: SignInFailureReason = message.includes("cancel")
      ? "cancelled"
      : message.includes("timed out")
        ? "timeout"
        : "error";
    analytics.track(ANALYTICS_EVENTS.SIGN_IN_FAILED, {
      method,
      region: selectedRegion,
      reason,
      error_message: message,
    });
  };

  // After successful sign-in, resume the originally-requested deep link if
  // there was one, otherwise drop into the default tab. Guards against `next`
  // pointing back at /auth (which would loop) or being a non-local URL.
  const navigateAfterLogin = useCallback(() => {
    const target =
      typeof next === "string" &&
      next.startsWith("/") &&
      !next.startsWith("/auth")
        ? next
        : "/(tabs)/tasks";
    router.replace(target);
  }, [next]);

  const handleQrScan = async (result: QrScanResult) => {
    setScannerVisible(false);
    setDevToken(result.apiKey);
    setDevProjectId(String(result.projectId));
    setIsLoading(true);
    setError(null);
    trackSignInStarted("qr_scan");
    try {
      await loginWithPersonalApiKey({
        token: result.apiKey,
        projectId: result.projectId,
        region: selectedRegion,
      });
      trackSignInCompleted("qr_scan");
      navigateAfterLogin();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to sign in";
      trackSignInFailed("qr_scan", message);
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDevSignIn = async () => {
    setIsLoading(true);
    setError(null);
    trackSignInStarted("dev_api_key");
    try {
      const projectIdNum = Number(devProjectId);
      if (!Number.isFinite(projectIdNum) || projectIdNum <= 0) {
        throw new Error("Project ID must be a positive number");
      }
      await loginWithPersonalApiKey({
        token: devToken,
        projectId: projectIdNum,
        region: selectedRegion,
      });
      trackSignInCompleted("dev_api_key");
      navigateAfterLogin();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to sign in";
      trackSignInFailed("dev_api_key", message);
      setError(message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignIn = async () => {
    setIsLoading(true);
    setError(null);
    trackSignInStarted("oauth");

    try {
      await loginWithOAuth(selectedRegion);
      trackSignInCompleted("oauth");
      // Navigate to tabs on success
      navigateAfterLogin();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to authenticate";
      trackSignInFailed("oauth", message);

      if (message.includes("cancelled") || message.includes("cancel")) {
        setError("Authorization cancelled.");
      } else if (message.includes("timed out")) {
        setError("Authorization timed out. Please try again.");
      } else {
        setError(message);
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <SafeAreaView className="flex-1 bg-gray-1">
      <ScrollView
        className="flex-1"
        contentContainerClassName="px-6 pt-16 pb-10"
        keyboardShouldPersistTaps="handled"
      >
        {/* Header */}
        <View className="mb-10">
          <Text className="mb-2 font-semibold text-2xl text-gray-12">
            PostHog Mobile
          </Text>
          <Text className="text-base text-gray-11">
            Sign in with your PostHog account
          </Text>
        </View>

        {/* Form */}
        <View className="gap-4">
          <Text className="mb-2 font-medium text-gray-11 text-sm">
            PostHog region
          </Text>

          {/* Region Picker */}
          <View className="mb-4 flex-row gap-3">
            {regions.map((region) => (
              <TouchableOpacity
                key={region.value}
                className={`flex-1 items-center rounded-lg border px-4 py-3 ${
                  selectedRegion === region.value
                    ? "border-accent-9 bg-accent-3"
                    : "border-gray-6 bg-gray-3"
                }`}
                onPress={() => setSelectedRegion(region.value)}
              >
                <Text
                  className={`font-medium text-sm ${
                    selectedRegion === region.value
                      ? "text-accent-11"
                      : "text-gray-11"
                  }`}
                >
                  {region.label}
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          {/* Error Message */}
          {error && (
            <View className="rounded-lg border border-status-error bg-status-error/10 p-3">
              <Text className="text-sm text-status-error">{error}</Text>
            </View>
          )}

          {/* Loading Message */}
          {isLoading && (
            <View className="rounded-lg border border-status-info bg-status-info/10 p-3">
              <Text className="text-sm text-status-info">
                Waiting for authorization in your browser...
              </Text>
            </View>
          )}

          {/* Sign In Button */}
          <TouchableOpacity
            className={`mt-2 items-center rounded-lg py-4 ${
              isLoading ? "bg-gray-7" : "bg-accent-9"
            }`}
            onPress={handleSignIn}
            disabled={isLoading}
          >
            {isLoading ? (
              <ActivityIndicator color={themeColors.gray[12]} />
            ) : (
              <Text className="font-semibold text-accent-contrast text-base">
                Sign in with PostHog
              </Text>
            )}
          </TouchableOpacity>

          {__DEV__ && (
            <View className="mt-8 gap-3 rounded-lg border border-gray-6 bg-gray-2 p-4">
              <Text className="font-semibold text-gray-12 text-sm">
                Dev sign-in (personal API key)
              </Text>
              <Text className="text-gray-11 text-xs">
                Skips OAuth. Create a personal API key at Settings → User API
                keys with scopes: user:read, project:read, task:write,
                integration:read, conversation:write, query:read,
                llm_skill:read.
              </Text>
              <TextInput
                value={devToken}
                onChangeText={setDevToken}
                placeholder="phx_..."
                placeholderTextColor={themeColors.gray[9]}
                autoCapitalize="none"
                autoCorrect={false}
                secureTextEntry
                className="rounded-md border border-gray-6 bg-gray-3 px-3 py-2 text-gray-12"
              />
              <TextInput
                value={devProjectId}
                onChangeText={setDevProjectId}
                placeholder="Project ID (e.g. 2)"
                placeholderTextColor={themeColors.gray[9]}
                keyboardType="number-pad"
                className="rounded-md border border-gray-6 bg-gray-3 px-3 py-2 text-gray-12"
              />
              <TouchableOpacity
                className={`items-center rounded-md py-3 ${
                  isLoading || !devToken || !devProjectId
                    ? "bg-gray-7"
                    : "bg-gray-9"
                }`}
                onPress={handleDevSignIn}
                disabled={isLoading || !devToken || !devProjectId}
              >
                <Text className="font-medium text-gray-12 text-sm">
                  Dev sign in
                </Text>
              </TouchableOpacity>
              <TouchableOpacity
                className="items-center rounded-md border border-gray-7 py-3"
                onPress={() => {
                  setError(null);
                  setScannerVisible(true);
                }}
                disabled={isLoading}
              >
                <Text className="font-medium text-gray-12 text-sm">
                  Scan QR code
                </Text>
              </TouchableOpacity>
            </View>
          )}
        </View>
      </ScrollView>
      <QrScanModal
        visible={scannerVisible}
        onClose={() => setScannerVisible(false)}
        onScan={handleQrScan}
      />
    </SafeAreaView>
  );
}
