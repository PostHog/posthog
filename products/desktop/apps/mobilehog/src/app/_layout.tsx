import { QueryClientProvider } from "@tanstack/react-query";
import { useFonts } from "expo-font";
import { Stack, useRouter, useSegments } from "expo-router";
import * as SplashScreen from "expo-splash-screen";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { AppState } from "react-native";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { KeyboardProvider } from "react-native-keyboard-controller";
import { getAccountQueryClient } from "@/lib/accountLifecycle";
import { sessionIdentity, useAuth } from "@/lib/auth";
import { usePushNotifications } from "@/lib/notifications";
import { usePrefs } from "@/lib/prefs";
import { keys } from "@/lib/queries";
import { useRepo } from "@/lib/repo";
import { useSeenReports } from "@/lib/reports";
import { useSessions } from "@/lib/session";
import { colors } from "@/lib/theme";

SplashScreen.preventAutoHideAsync().catch(() => {});

function AuthGate() {
  const { session, hydrated, hydrate } = useAuth();
  const segments = useSegments();
  const router = useRouter();

  const hydrateRepo = useRepo((s) => s.hydrate);
  const hydratePrefs = usePrefs((s) => s.hydrate);
  const hydrateSeen = useSeenReports((s) => s.hydrate);
  usePushNotifications();
  useEffect(() => {
    hydrate();
    hydratePrefs();
  }, [hydrate, hydratePrefs]);

  useEffect(() => {
    if (!useAuth.getState().session) return;
    hydrateRepo();
    hydrateSeen();
  }, [hydrateRepo, hydrateSeen]);

  useEffect(() => {
    if (!hydrated) return;
    const onLogin = segments[0] === "login";
    if (!session && !onLogin) router.replace("/login");
    if (session && onLogin) router.replace("/(drawer)");
    SplashScreen.hideAsync().catch(() => {});
  }, [hydrated, session, segments, router]);

  return null;
}

export default function RootLayout() {
  const identity = useAuth(sessionIdentity);
  const [fontsLoaded, fontError] = useFonts({
    "JetBrainsMono-Regular": require("../../assets/fonts/JetBrainsMono-Regular.ttf"),
    "JetBrainsMono-Medium": require("../../assets/fonts/JetBrainsMono-Medium.ttf"),
    RoundHog: require("../../assets/fonts/RoundHog.ttf"),
    "RoundHog-Medium": require("../../assets/fonts/RoundHog-Medium.ttf"),
    "RoundHog-SemiBold": require("../../assets/fonts/RoundHog-SemiBold.ttf"),
    "RoundHog-Bold": require("../../assets/fonts/RoundHog-Bold.ttf"),
    "RoundHog-Italic": require("../../assets/fonts/RoundHog-Italic.ttf"),
  });
  const reconnect = useSessions((s) => s.reconnect);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        reconnect();
        const client = getAccountQueryClient();
        void client.invalidateQueries({ queryKey: keys.tasks });
        void client.invalidateQueries({ queryKey: keys.channels });
      }
    });
    return () => subscription.remove();
  }, [reconnect]);

  // Keep going after a font error and accept fallback fonts. AuthGate hides
  // the splash screen, and it cannot mount while this returns null.
  if (!fontsLoaded && !fontError) return null;

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: colors.bg }}>
      <KeyboardProvider>
        <QueryClientProvider key={identity} client={getAccountQueryClient()}>
          <StatusBar style="auto" />
          <AuthGate />
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: colors.bg },
            }}
          >
            <Stack.Screen name="login" options={{ animation: "fade" }} />
            <Stack.Screen name="(drawer)" />
            <Stack.Screen
              name="config"
              options={{
                presentation: "formSheet",
                sheetAllowedDetents: [0.6, 1],
                sheetGrabberVisible: true,
                sheetCornerRadius: 32,
                contentStyle: { backgroundColor: colors.bg },
              }}
            />
            <Stack.Screen
              name="picker"
              options={{
                presentation: "formSheet",
                sheetAllowedDetents: [0.55, 1],
                sheetGrabberVisible: true,
                sheetCornerRadius: 32,
                contentStyle: { backgroundColor: colors.bg },
              }}
            />
            <Stack.Screen
              name="search"
              options={{
                presentation: "fullScreenModal",
                animation: "slide_from_bottom",
              }}
            />
            <Stack.Screen
              name="space"
              options={{
                presentation: "formSheet",
                sheetAllowedDetents: [0.55, 1],
                sheetGrabberVisible: true,
                sheetCornerRadius: 32,
                contentStyle: { backgroundColor: colors.bg },
              }}
            />
            <Stack.Screen
              name="settings"
              options={{
                presentation: "modal",
                contentStyle: { backgroundColor: colors.bg },
              }}
            />
          </Stack>
        </QueryClientProvider>
      </KeyboardProvider>
    </GestureHandlerRootView>
  );
}
