import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Text,
} from "@posthog/quill";
import { type CloudRegion, REGION_LABELS } from "@posthog/shared";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";

interface RegionSelectProps {
  region: CloudRegion;
  onRegionChange: (region: CloudRegion) => void;
  disabled?: boolean;
  /** Host decides whether the local "dev" region is offered (e.g. dev builds). */
  includeDevRegion?: boolean;
}

const CLOUD_REGIONS: CloudRegion[] = ["us", "eu"];

function RegionOptionLabel({ region }: { region: CloudRegion }) {
  const { flag, label } = REGION_LABELS[region];
  return (
    <span className="flex items-center gap-2">
      <span className="shrink-0 leading-none">{flag}</span>
      <span>{label}</span>
    </span>
  );
}

export function RegionSelect({
  region,
  onRegionChange,
  disabled = false,
  includeDevRegion = false,
}: RegionSelectProps) {
  const offered: CloudRegion[] = includeDevRegion
    ? [...CLOUD_REGIONS, "dev"]
    : CLOUD_REGIONS;

  return (
    <div className="flex items-center justify-center gap-2">
      <Tooltip content="Where your PostHog data is stored. You can migrate later.">
        <Text className="text-(--gray-11) text-xs">Data region</Text>
      </Tooltip>
      <Select
        value={region}
        onValueChange={(next: CloudRegion | null) =>
          next && onRegionChange(next)
        }
        items={offered.map((candidate) => ({
          value: candidate,
          label: REGION_LABELS[candidate].label,
        }))}
      >
        {/* Fixed width so switching regions never reflows the row beneath the button. */}
        <SelectTrigger
          size="sm"
          disabled={disabled}
          aria-label="Data region"
          className="w-[176px]"
        >
          <SelectValue>
            <RegionOptionLabel region={region} />
          </SelectValue>
        </SelectTrigger>
        <SelectContent align="center" side="bottom" sideOffset={6}>
          {offered.map((candidate) => (
            <SelectItem key={candidate} value={candidate}>
              <RegionOptionLabel region={candidate} />
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
