import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Text,
} from "@posthog/quill";
import { type CloudRegion, describeRegion } from "@posthog/shared";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";

interface RegionSelectProps {
  region: CloudRegion;
  onRegionChange: (region: CloudRegion) => void;
  disabled?: boolean;
  /** Host decides whether development regions are offered. */
  includeDevRegion?: boolean;
}

const PRODUCTION_REGIONS: CloudRegion[] = ["us", "eu"];
const DEVELOPMENT_REGIONS: CloudRegion[] = ["dev-cloud", "dev", "custom"];

export function getSelectableRegions(includeDevRegion: boolean): CloudRegion[] {
  return includeDevRegion
    ? [...PRODUCTION_REGIONS, ...DEVELOPMENT_REGIONS]
    : PRODUCTION_REGIONS;
}

function RegionOptionLabel({ region }: { region: CloudRegion }) {
  const { flag, hint, label } = describeRegion(region);
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="shrink-0 leading-none">{flag}</span>
      <span className="shrink-0 font-medium">{label}</span>
      <span className="truncate text-(--gray-10) text-xs">{hint}</span>
    </span>
  );
}

export function RegionSelect({
  region,
  onRegionChange,
  disabled = false,
  includeDevRegion = false,
}: RegionSelectProps) {
  const offered = getSelectableRegions(includeDevRegion);

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
          label: `${describeRegion(candidate).label} - ${describeRegion(candidate).hint}`,
        }))}
      >
        {/* Fixed width so switching regions never reflows the row beneath the button. */}
        <SelectTrigger
          size="sm"
          disabled={disabled}
          aria-label="Data region"
          className="w-[280px]"
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
