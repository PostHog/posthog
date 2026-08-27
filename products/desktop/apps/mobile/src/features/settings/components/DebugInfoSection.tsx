import { Text } from "@components/text";
import * as Application from "expo-application";
import * as Clipboard from "expo-clipboard";
import Constants from "expo-constants";
import * as Haptics from "expo-haptics";
import { Copy } from "phosphor-react-native";
import { useState } from "react";
import { Platform, Pressable, View } from "react-native";
import { useThemeColors } from "@/lib/theme";
import { SettingsRow } from "./SettingsRow";
import { SettingsSection } from "./SettingsSection";

interface DebugInfoSectionProps {
  cloudRegion: string | null;
  projectId: number | null;
  userId?: number;
  userUuid?: string;
}

/**
 * Staff-only diagnostics shown at the bottom of Settings. Surfaces the build /
 * version identifiers we need to tell exactly which binary a user is running
 * (native app version + build number, runtime version, EAS project, execution
 * environment) plus the active region/project/user. Gate rendering on
 * `is_staff` at the call site — this component does not check itself.
 */
export function DebugInfoSection({
  cloudRegion,
  projectId,
  userId,
  userUuid,
}: DebugInfoSectionProps) {
  const themeColors = useThemeColors();
  const [copied, setCopied] = useState(false);

  const appVersion =
    Application.nativeApplicationVersion ??
    Constants.expoConfig?.version ??
    "—";
  const buildVersion = Application.nativeBuildVersion ?? "—";
  const bundleId = Application.applicationId ?? "—";
  const runtimeVersion =
    typeof Constants.expoConfig?.runtimeVersion === "string"
      ? Constants.expoConfig.runtimeVersion
      : "—";
  const easProjectId =
    (Constants.expoConfig?.extra?.eas?.projectId as string | undefined) ?? "—";
  const platform = `${Platform.OS} ${String(Platform.Version)}`;
  const executionEnv = Constants.executionEnvironment ?? "—";
  const buildType = __DEV__ ? "development" : "production";

  // Build-number label differs by platform (iOS buildNumber vs Android
  // versionCode) — name it so staff aren't guessing which they're reading.
  const buildLabel =
    Platform.OS === "android" ? "Version code" : "Build number";

  const rows: Array<{ label: string; value: string }> = [
    { label: "App version", value: appVersion },
    { label: buildLabel, value: buildVersion },
    { label: "Runtime version", value: runtimeVersion },
    { label: "Build type", value: buildType },
    { label: "Execution env", value: executionEnv },
    { label: "Platform", value: platform },
    { label: "Bundle ID", value: bundleId },
    { label: "EAS project", value: easProjectId },
    { label: "Region", value: cloudRegion?.toUpperCase() ?? "—" },
    { label: "Project ID", value: projectId != null ? String(projectId) : "—" },
    { label: "User ID", value: userId != null ? String(userId) : "—" },
    { label: "User UUID", value: userUuid ?? "—" },
  ];

  const handleCopy = async () => {
    const payload = rows.map((r) => `${r.label}: ${r.value}`).join("\n");
    await Clipboard.setStringAsync(payload);
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(
      () => {},
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <SettingsSection
      title="Debug info"
      description="Staff only — useful for identifying which build this is"
    >
      {rows.map((row, index) => (
        <SettingsRow
          key={row.label}
          label={row.label}
          showDivider={index < rows.length - 1}
          rightSlot={
            <Text
              className="max-w-[220px] text-right text-[13px] text-gray-11"
              numberOfLines={1}
              selectable
            >
              {row.value}
            </Text>
          }
        />
      ))}
      <View className="border-gray-5 border-t px-4 py-3">
        <Pressable
          onPress={handleCopy}
          hitSlop={6}
          className="flex-row items-center justify-center gap-2 rounded-md border border-gray-6 bg-gray-3 py-2.5 active:opacity-60"
        >
          <Copy size={15} color={themeColors.gray[12]} />
          <Text className="font-medium text-[14px] text-gray-12">
            {copied ? "Copied!" : "Copy debug info"}
          </Text>
        </Pressable>
      </View>
    </SettingsSection>
  );
}
