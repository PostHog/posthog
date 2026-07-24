import { Text } from "@components/text";
import { Cube } from "phosphor-react-native";
import { View } from "react-native";
import { toRgba } from "@/lib/theme";
import { useCustomImageName } from "../hooks/useCustomImageName";
import type { Task } from "../types";

// Theme tokens have no violet; a fixed Radix violet-9 mirrors the desktop
// custom-image badge and reads well in both light and dark.
const VIOLET = "#6e56cf";

export function CustomImageBadge({ task }: { task: Task }) {
  const run = task.latest_run;
  const state = run?.state as
    | { custom_image_id?: unknown; sandbox_environment_id?: unknown }
    | undefined;
  const customImageId =
    typeof state?.custom_image_id === "string" ? state.custom_image_id : null;
  const sandboxEnvironmentId =
    typeof state?.sandbox_environment_id === "string"
      ? state.sandbox_environment_id
      : null;

  const imageName = useCustomImageName({
    customImageId,
    sandboxEnvironmentId,
    enabled: run?.environment === "cloud",
  });

  if (!imageName) return null;

  return (
    <View
      className="h-9 max-w-[160px] flex-row items-center gap-1 rounded-lg border px-2.5"
      style={{
        backgroundColor: toRgba(VIOLET, 0.12),
        borderColor: toRgba(VIOLET, 0.35),
      }}
      accessibilityRole="text"
      accessibilityLabel={`Runs on custom base image "${imageName}"`}
    >
      <Cube size={14} weight="fill" color={VIOLET} />
      <Text
        numberOfLines={1}
        className="font-semibold text-[13px]"
        style={{ color: VIOLET }}
      >
        {imageName}
      </Text>
    </View>
  );
}
