import { type CloudRegion, REGION_LABELS } from "@posthog/shared";
import { Flex, Text } from "@radix-ui/themes";

interface RegionSelectProps {
  region: CloudRegion;
  onRegionChange: (region: CloudRegion) => void;
  disabled?: boolean;
  /** Host decides whether the local "dev" region is offered (e.g. dev builds). */
  includeDevRegion?: boolean;
}

const LOGIN_GRID_REGIONS: CloudRegion[] = ["us", "eu"];

export function RegionSelect({
  region,
  onRegionChange,
  disabled = false,
  includeDevRegion = false,
}: RegionSelectProps) {
  return (
    <Flex direction="column" gap="2" className="w-full">
      <Flex justify="between" align="center">
        <Text className="font-medium text-(--gray-12) text-sm">
          PostHog region
        </Text>
        <Text className="text-(--gray-11) text-xs">
          Pick where your data lives
        </Text>
      </Flex>
      <div className="grid w-full grid-cols-2 gap-2">
        {LOGIN_GRID_REGIONS.map((regionKey) => (
          <RegionPickerOptionButton
            key={regionKey}
            regionKey={regionKey}
            selected={regionKey === region}
            disabled={disabled}
            onSelect={() => onRegionChange(regionKey)}
          />
        ))}
      </div>
      {includeDevRegion && (
        <RegionPickerOptionButton
          regionKey="dev"
          selected={region === "dev"}
          disabled={disabled}
          onSelect={() => onRegionChange("dev")}
        />
      )}
    </Flex>
  );
}

function RegionPickerOptionButton({
  regionKey,
  selected,
  disabled,
  onSelect,
}: {
  regionKey: CloudRegion;
  selected: boolean;
  disabled: boolean;
  onSelect: () => void;
}) {
  const { flag, label, hint } = REGION_LABELS[regionKey];
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      disabled={disabled}
      className={`flex w-full flex-col items-start gap-[2px] rounded-[8px] border-[1.5px] px-3 py-2 text-left transition-colors ${
        selected
          ? "border-(--accent-9) bg-(--accent-3) text-(--gray-12)"
          : "border-(--gray-6) bg-transparent text-(--gray-12) hover:border-(--gray-8)"
      } ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
    >
      <Flex align="center" gap="2" className="w-full">
        <span className="text-[18px] leading-none">{flag}</span>
        <Text className="font-semibold text-(--gray-12) text-sm">{label}</Text>
      </Flex>
      <Text className="pl-[26px] text-(--gray-11) text-xs">{hint}</Text>
    </button>
  );
}
