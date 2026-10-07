import { Stack } from "expo-router";
import { colors } from "@/lib/theme";

// Settings drills down with native pushes inside the modal.
export default function SettingsLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.bg },
      }}
    />
  );
}
