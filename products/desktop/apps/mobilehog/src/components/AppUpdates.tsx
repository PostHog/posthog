import * as Application from "expo-application";
import Constants from "expo-constants";
import * as Updates from "expo-updates";
import { useState } from "react";
import { Alert, Pressable, Text, View } from "react-native";
import { captureFailure } from "@/lib/analytics";
import { colors, fonts } from "@/lib/theme";

export function AppUpdates() {
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [message, setMessage] = useState("");
  const check = async (): Promise<void> => {
    setBusy(true);
    setMessage("");
    try {
      const result = await Updates.checkForUpdateAsync();
      if (result.isAvailable) {
        await Updates.fetchUpdateAsync();
        setReady(true);
        setMessage("Update ready. Restart when you are ready.");
      } else setMessage("You have the latest compatible update.");
    } catch (error) {
      setMessage(
        "Could not check for updates. Check your connection and try again.",
      );
      captureFailure("check_update", error);
    } finally {
      setBusy(false);
    }
  };
  return (
    <View
      style={{
        padding: 18,
        gap: 12,
        borderRadius: 20,
        backgroundColor: colors.surface,
      }}
    >
      <Text
        style={{
          color: colors.ink,
          fontFamily: fonts.sansMedium,
          fontSize: 16,
        }}
      >
        Version{" "}
        {Application.nativeApplicationVersion ?? Constants.expoConfig?.version}
        {Application.nativeBuildVersion
          ? ` (${Application.nativeBuildVersion})`
          : ""}
      </Text>
      {Updates.isEnabled ? (
        <Pressable
          accessibilityRole="button"
          disabled={busy}
          style={{ minHeight: 44, justifyContent: "center" }}
          onPress={() =>
            ready
              ? Alert.alert(
                  "Restart posthog?",
                  "The update will close the current screen. Your saved drafts will remain on this device.",
                  [
                    { text: "Later", style: "cancel" },
                    {
                      text: "Restart",
                      onPress: () =>
                        void Updates.reloadAsync().catch((error) => {
                          setMessage(
                            "Could not restart. Close and open the app.",
                          );
                          captureFailure("apply_update", error);
                        }),
                    },
                  ],
                )
              : void check()
          }
        >
          <Text style={{ color: colors.accent, fontSize: 16 }}>
            {busy
              ? "Checking"
              : ready
                ? "Restart to update"
                : "Check for updates"}
          </Text>
        </Pressable>
      ) : null}
      {message ? (
        <Text
          accessibilityLiveRegion="polite"
          style={{ color: colors.inkSoft, fontSize: 14 }}
        >
          {message}
        </Text>
      ) : null}
    </View>
  );
}
