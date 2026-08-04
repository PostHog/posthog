import "../../global.css";
import "@/lib/textDefaults";

import { QueryClientProvider } from "@tanstack/react-query";
import { router, Stack, usePathname } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useColorScheme } from "nativewind";
import { PostHogProvider } from "posthog-react-native";
import { useEffect } from "react";
import { ActivityIndicator, View } from "react-native";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { SafeAreaProvider } from "react-native-safe-area-context";
import {
  OFFLINE_BANNER_HEIGHT,
  OfflineBanner,
} from "@/components/OfflineBanner";
import { useAuthStore } from "@/features/auth";
import { setupNotificationResponseListener } from "@/features/notifications/lib/notifications";
import { usePreferencesStore } from "@/features/preferences/stores/preferencesStore";
import { PendingPromptRecovery } from "@/features/tasks/components/PendingPromptRecovery";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import {
  POSTHOG_API_KEY,
  POSTHOG_OPTIONS,
  useIdentifyUser,
  useRegisterSuperProperties,
  useScreenTracking,
} from "@/lib/posthog";
import { queryClient } from "@/lib/queryClient";
import { darkTheme, lightTheme, useThemeColors } from "@/lib/theme";

interface RootLayoutNavProps {
  isConnected: boolean;
}

function RootLayoutNav({ isConnected }: RootLayoutNavProps) {
  const { isAuthenticated, isLoading, initializeAuth } = useAuthStore();
  const themeColors = useThemeColors();
  const pathname = usePathname();

  useScreenTracking();
  useIdentifyUser();
  useRegisterSuperProperties();

  useEffect(() => {
    initializeAuth();
  }, [initializeAuth]);

  useEffect(() => {
    return setupNotificationResponseListener(({ path }) => {
      router.push(path);
    });
  }, []);

  // Auth gate. If a deep link drops an unauthed user on a protected route
  // (e.g. `posthog://task/abc` from a notification or shared link), bounce
  // them to /auth with a `next` param so the sign-in flow can resume the
  // originally-intended navigation.
  useEffect(() => {
    if (isLoading) return;
    if (isAuthenticated) return;
    if (!pathname || pathname === "/auth") return;
    const next = pathname !== "/" ? pathname : undefined;
    router.replace(next ? { pathname: "/auth", params: { next } } : "/auth");
  }, [isAuthenticated, isLoading, pathname]);

  if (isLoading) {
    return (
      <View className="flex-1 items-center justify-center bg-background">
        <ActivityIndicator size="large" color={themeColors.accent[9]} />
      </View>
    );
  }

  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: {
          backgroundColor: themeColors.background,
          paddingTop: isConnected ? 0 : OFFLINE_BANNER_HEIGHT,
        },
      }}
    >
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      <Stack.Screen name="auth" options={{ headerShown: false }} />
      <Stack.Screen name="index" options={{ headerShown: false }} />

      {/* Tinder-style inbox review */}
      <Stack.Screen name="review" options={{ headerShown: false }} />

      {/* Settings — pushed on top of whatever the user was viewing, so
          back / iOS swipe-back / Android hardware-back all return to it. */}
      <Stack.Screen name="settings/index" options={{ headerShown: false }} />

      {/* MCP servers — marketplace + installed management. */}
      <Stack.Screen name="mcp-servers/index" options={{ headerShown: false }} />
      <Stack.Screen
        name="mcp-servers/add-custom"
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="mcp-servers/template/[id]"
        options={{ headerShown: false }}
      />
      <Stack.Screen
        name="mcp-servers/installation/[id]"
        options={{ headerShown: false }}
      />

      {/* Inbox report detail - modal presentation, no native header
          (the in-content title block is the canonical header). Catch-all
          segment so the route also tolerates the cosmetic slug suffix on
          shared links: `posthog://inbox/<reportId>` and
          `posthog://inbox/<reportId>/<slug>` both resolve here. */}
      <Stack.Screen
        name="inbox/[...id]"
        options={{ presentation: "modal", headerShown: false }}
      />

      {/* Task routes - modal presentation, no native header. */}
      <Stack.Screen
        name="task/index"
        options={{ presentation: "modal", headerShown: false }}
      />
      <Stack.Screen
        name="task/[id]"
        options={{ presentation: "modal", headerShown: false }}
      />
      <Stack.Screen
        name="automation/index"
        options={{
          presentation: "modal",
          headerShown: true,
          title: "Create automation",
          headerStyle: { backgroundColor: themeColors.background },
          headerTintColor: themeColors.gray[12],
        }}
      />
      <Stack.Screen
        name="automation/create"
        options={{
          presentation: "modal",
          headerShown: true,
          title: "New automation",
          headerStyle: { backgroundColor: themeColors.background },
          headerTintColor: themeColors.gray[12],
        }}
      />
      <Stack.Screen
        name="automation/[id]"
        options={{
          presentation: "modal",
          headerShown: true,
          headerStyle: { backgroundColor: themeColors.background },
          headerTintColor: themeColors.gray[12],
        }}
      />
      <Stack.Screen
        name="pr-diff"
        options={{
          presentation: "modal",
          headerShown: true,
          title: "Files changed",
          headerStyle: { backgroundColor: themeColors.background },
          headerTintColor: themeColors.gray[12],
        }}
      />
    </Stack>
  );
}

export default function RootLayout() {
  const { colorScheme, setColorScheme } = useColorScheme();
  const themePreference = usePreferencesStore((s) => s.theme);

  // Sync the user's theme preference into NativeWind's color scheme so the
  // entire app honours it (including light/dark/system).
  useEffect(() => {
    setColorScheme(themePreference);
  }, [themePreference, setColorScheme]);

  const themeVars = colorScheme === "dark" ? darkTheme : lightTheme;
  const { isConnected } = useNetworkStatus();

  return (
    <SafeAreaProvider>
      <KeyboardProvider>
        <PostHogProvider
          apiKey={POSTHOG_API_KEY}
          options={POSTHOG_OPTIONS}
          autocapture={{
            captureTouches: true,
            captureScreens: false, // We handle screen tracking manually for expo-router
          }}
        >
          <QueryClientProvider client={queryClient}>
            <View style={themeVars} className="flex-1">
              <RootLayoutNav isConnected={isConnected} />
              <OfflineBanner isConnected={isConnected} />
              <PendingPromptRecovery />
            </View>
            <StatusBar style={colorScheme === "dark" ? "light" : "dark"} />
          </QueryClientProvider>
        </PostHogProvider>
      </KeyboardProvider>
    </SafeAreaProvider>
  );
}
