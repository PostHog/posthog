import { CheckIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { SearchInput } from "@posthog/ui/primitives/SearchInput";
import type {
  LoopCounts,
  LoopListFilters,
  LoopScopeFilter,
} from "../loopListFilters";

export function LoopsFilterBar({
  filters,
  counts,
  showScope,
  onChange,
}: {
  filters: LoopListFilters;
  counts: LoopCounts;
  showScope: boolean;
  onChange: (patch: Partial<LoopListFilters>) => void;
}) {
  const summary = [`${counts.active} active`];
  if (showScope) {
    summary.push(`${counts.global} global`);
    if (counts.spaces > 0) {
      summary.push(
        `${counts.total - counts.global} in ${counts.spaces} space${counts.spaces === 1 ? "" : "s"}`,
      );
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {showScope ? (
        <SettingsOptionSelect
          value={filters.scope}
          options={[
            { value: "all", label: `All loops (${counts.total})` },
            { value: "global", label: `Global loops (${counts.global})` },
          ]}
          onValueChange={(value) =>
            onChange({ scope: value as LoopScopeFilter })
          }
          size="default"
          ariaLabel="Filter by scope"
          className="h-8 w-44"
        />
      ) : null}
      <SearchInput
        className="w-64"
        value={filters.search}
        onValueChange={(search) => onChange({ search })}
        placeholder="Search loops"
      />
      <Button
        type="button"
        variant={filters.hidePaused ? "outline" : "link-muted"}
        size="default"
        className="h-8"
        onClick={() => onChange({ hidePaused: !filters.hidePaused })}
      >
        {filters.hidePaused ? <CheckIcon size={12} /> : null}
        Hide paused
      </Button>
      <span className="ml-auto text-[12px] text-gray-10">
        {summary.join(" · ")}
      </span>
    </div>
  );
}
