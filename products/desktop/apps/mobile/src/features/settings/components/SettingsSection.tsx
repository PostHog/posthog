import { Text } from "@components/text";
import type { ReactNode } from "react";
import { View } from "react-native";

interface SettingsSectionProps {
  title: string;
  description?: string;
  children: ReactNode;
}

/**
 * Grouped section of setting rows. Renders a labelled title above a rounded
 * card. Mirrors the desktop `SettingRow` grouping pattern: a small section
 * heading and an outlined panel of rows below it.
 */
export function SettingsSection({
  title,
  description,
  children,
}: SettingsSectionProps) {
  return (
    <View className="mb-6">
      <Text className="mb-2 px-1 font-medium text-[13px] text-gray-11 uppercase">
        {title}
      </Text>
      {description ? (
        <Text className="mb-2 px-1 text-[12px] text-gray-10 leading-snug">
          {description}
        </Text>
      ) : null}
      <View className="overflow-hidden rounded-2xl border border-gray-5 bg-card">
        {children}
      </View>
    </View>
  );
}
