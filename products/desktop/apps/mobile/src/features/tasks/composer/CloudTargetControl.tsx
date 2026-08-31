import { Cloud } from "phosphor-react-native";
import { useState } from "react";
import { useThemeColors } from "@/lib/theme";
import {
  type CloudTarget,
  type CloudTargetOption,
  cloudTargetFromKey,
  cloudTargetKey,
} from "./cloudTargets";
import { Pill } from "./Pill";
import { SelectSheet } from "./SelectSheet";

interface CloudTargetControlProps {
  cloudTarget: CloudTarget;
  onCloudTargetChange: (target: CloudTarget) => void;
  options: CloudTargetOption[];
  favoriteKey: string | null;
  onToggleFavorite: (target: CloudTarget) => void;
  disabled?: boolean;
}

export function CloudTargetControl({
  cloudTarget,
  onCloudTargetChange,
  options,
  favoriteKey,
  onToggleFavorite,
  disabled,
}: CloudTargetControlProps) {
  const themeColors = useThemeColors();
  const [sheetOpen, setSheetOpen] = useState(false);

  const currentKey = cloudTargetKey(cloudTarget);
  const currentName =
    options.find((option) => option.key === currentKey)?.name ?? "Default";

  return (
    <>
      <Pill
        icon={<Cloud size={14} color={themeColors.gray[11]} />}
        label={currentName}
        onPress={() => setSheetOpen(true)}
        disabled={disabled}
      />

      <SelectSheet
        open={sheetOpen}
        title="Cloud sandbox"
        value={currentKey}
        favoriteValue={favoriteKey}
        onChange={(next) => {
          const target = cloudTargetFromKey(next);
          if (target) onCloudTargetChange(target);
        }}
        onToggleFavorite={(next) => {
          const target = cloudTargetFromKey(next);
          if (target) onToggleFavorite(target);
        }}
        onClose={() => setSheetOpen(false)}
        options={options.map((option) => ({
          value: option.key,
          label: option.name,
          description: option.description,
        }))}
      />
    </>
  );
}
