import { Stack } from "expo-router";
import { colors } from "@/lib/theme";

// The run options sheet drills down with native pushes inside the sheet.
export default function ConfigLayout() {
  return (
    <Stack
      screenOptions={{
        headerShown: false,
        contentStyle: { backgroundColor: colors.bg },
      }}
    />
  );
}
