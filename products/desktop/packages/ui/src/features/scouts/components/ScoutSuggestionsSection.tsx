import {
  ArrowsClockwiseIcon,
  CaretDownIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
import type {
  ScoutSuggestionItem,
  ScoutSuggestionSet,
} from "@posthog/api-client/posthog-client";
import { visibleScoutSuggestions } from "@posthog/core/scouts/scoutSuggestions";
import { Button, Skeleton } from "@posthog/quill";
import type { ScoutSuggestionSurface } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useMemo, useRef, useState } from "react";
import { useScoutConfigs } from "../hooks/useScoutConfigs";
import type { ScoutSuggestionActions } from "../hooks/useScoutSuggestionActions";
import { useScoutSuggestionActions } from "../hooks/useScoutSuggestionActions";
import { useScoutSuggestions } from "../hooks/useScoutSuggestions";
import { ScoutSuggestionCard } from "./ScoutSuggestionCard";

/** Titles named on the collapsed line before it gives up and counts the rest. */
const COLLAPSED_TITLE_PREVIEW = 2;

/**
 * A project that has never been scanned has nothing to show and no refresh worth
 * offering. A scan that found nothing still counts: it has a `generated_at`, and
 * the person needs the Refresh to ask again once there is more data. So does a
 * first scan that failed, which has no `generated_at` at all.
 */
function hasBatch(set: ScoutSuggestionSet | null | undefined): boolean {
  if (!set) return false;
  return (
    set.generated_at !== null || set.items.length > 0 || set.status === "failed"
  );
}

/**
 * The "Suggested for this project" section above the scout roster: a
 * pre-computed batch of scouts worth running here, each ready to turn on or
 * create with no wait for a scan.
 *
 * Nothing renders until a batch exists, so a project that has never been scanned
 * sees the roster exactly as it was. `stale` is a footer note rather than an
 * error: any fleet change flips it and the picks stay valid.
 */
export function ScoutSuggestionsSection() {
  const suggestions = useScoutSuggestionsSurface("strip");
  if (!hasBatch(suggestions.suggestionSet)) return null;
  return <ScoutSuggestionsSectionView {...suggestions} />;
}

/**
 * The cards on their own, for the empty state's body: a project with no scouts
 * yet gets the picks as the thing to act on.
 */
export function ScoutSuggestionsCards() {
  const suggestions = useScoutSuggestionsSurface("empty_state");
  if (!hasBatch(suggestions.suggestionSet) || suggestions.items.length === 0) {
    return null;
  }
  return (
    <div className="@container flex w-full flex-col gap-3">
      <SuggestionGrid {...suggestions} />
    </div>
  );
}

export interface ScoutSuggestionsViewProps {
  /** The picks still worth offering, dismissed and enabled ones already dropped. */
  items: ScoutSuggestionItem[];
  suggestionSet: ScoutSuggestionSet | null | undefined;
  isLoading: boolean;
  surface: ScoutSuggestionSurface;
  actions: ScoutSuggestionActions;
}

/** Query, visibility filter, actions and the impression event, in one place. */
function useScoutSuggestionsSurface(
  surface: ScoutSuggestionSurface,
): ScoutSuggestionsViewProps {
  const { data: configs } = useScoutConfigs();
  const [isScanning, setIsScanning] = useState(false);
  const { data: suggestionSet, isLoading } = useScoutSuggestions({
    isScanning,
  });
  const actions = useScoutSuggestionActions({ surface, suggestionSet });
  const items = useMemo(
    () =>
      visibleScoutSuggestions(suggestionSet?.items ?? [], {
        hiddenIds: actions.hiddenIds,
        configs: configs ?? [],
      }),
    [suggestionSet, actions.hiddenIds, configs],
  );

  // The query polls only while a scan runs, and the actions hook is what knows
  // when that scan started and settled.
  useEffect(() => setIsScanning(actions.isScanning), [actions.isScanning]);

  const reported = useRef(false);
  useEffect(() => {
    if (reported.current || !hasBatch(suggestionSet)) return;
    reported.current = true;
    track(ANALYTICS_EVENTS.SCOUT_SUGGESTIONS_SHOWN, {
      suggestion_count: items.length,
      batch_status: suggestionSet?.status ?? "empty",
      batch_age_hours: batchAgeHours(suggestionSet),
      collapsed: false,
      surface,
    });
  }, [suggestionSet, items, surface]);

  return { items, suggestionSet, isLoading, surface, actions };
}

function batchAgeHours(
  set: ScoutSuggestionSet | null | undefined,
): number | null {
  if (!set?.generated_at) return null;
  const hours = (Date.now() - new Date(set.generated_at).getTime()) / 3_600_000;
  return Math.max(0, Math.round(hours * 10) / 10);
}

/** The section as it renders, with its data supplied (Storybook renders this directly). */
export function ScoutSuggestionsSectionView(props: ScoutSuggestionsViewProps) {
  const { items, suggestionSet, actions } = props;
  const [collapsed, setCollapsed] = useState(false);
  const generatedAt = suggestionSet?.generated_at;

  return (
    <section className="@container flex flex-col gap-3 rounded-(--radius-3) border border-border bg-(--gray-2) p-3">
      <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <div className="flex items-center gap-1.5">
            <SparkleIcon size={14} className="text-(--iris-9)" />
            <h3 className="m-0 font-medium text-[13px] text-gray-12">
              Suggested for this project
            </h3>
            {items.length > 0 ? (
              <span className="text-[12px] text-gray-10 tabular-nums">
                {items.length}
              </span>
            ) : null}
          </div>
          <span className="text-[12px] text-gray-11">
            Picked by scanning this project's data against the scouts you
            already run.
            {generatedAt ? (
              <>
                {" Refreshed "}
                <RelativeTimestamp timestamp={generatedAt} />.
              </>
            ) : null}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            type="button"
            size="xs"
            variant="outline"
            loading={actions.isScanning}
            onClick={() => void actions.refresh()}
          >
            <ArrowsClockwiseIcon size={12} />
            Refresh
          </Button>
          <Button
            type="button"
            size="icon-xs"
            variant="default"
            aria-label={
              collapsed ? "Show suggested scouts" : "Hide suggested scouts"
            }
            aria-expanded={!collapsed}
            onClick={() => setCollapsed((value) => !value)}
          >
            <CaretDownIcon
              size={12}
              className={collapsed ? "-rotate-90" : undefined}
            />
          </Button>
        </div>
      </div>
      {collapsed ? (
        <CollapsedLine titles={items.map((item) => item.title)} />
      ) : (
        <SectionBody {...props} />
      )}
    </section>
  );
}

/** Whichever of the open section's three states applies: scanning, nothing left, or the cards. */
function SectionBody(props: ScoutSuggestionsViewProps) {
  const { items, suggestionSet, isLoading, actions } = props;

  if (actions.isScanning || (isLoading && items.length === 0)) {
    return <SuggestionsSkeleton />;
  }
  if (items.length === 0) {
    return (
      <p className="m-0 text-[12px] text-gray-11">
        {suggestionSet?.status === "failed"
          ? "The last scan didn't finish, so there are no picks yet. Refresh to try again."
          : "Nothing left to suggest right now. Refresh to scan the project again."}
      </p>
    );
  }
  return (
    <>
      <SuggestionGrid {...props} />
      {suggestionSet?.status === "stale" ? (
        <span className="text-[11px] text-gray-10">
          Your scouts changed since these were picked, or the picks are due a
          refresh, so some may already be covered.
        </span>
      ) : null}
      {suggestionSet?.status === "failed" ? (
        <span className="text-[11px] text-gray-10">
          The last scan didn't finish, so these are the picks from before it.
        </span>
      ) : null}
    </>
  );
}

function SuggestionGrid({
  items,
  surface,
  actions,
}: ScoutSuggestionsViewProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <div
      className={`grid grid-cols-1 items-stretch gap-2 ${
        // One card in a three-across grid reads as a gap where the other two
        // should be, so a lone card keeps a single narrow column.
        items.length === 1 ? "max-w-md" : "@2xl:grid-cols-2 @4xl:grid-cols-3"
      }`}
    >
      {items.map((item) => (
        <ScoutSuggestionCard
          key={item.id}
          item={item}
          surface={surface}
          isBusy={actions.busyIds.includes(item.id)}
          isExpanded={expandedId === item.id}
          onToggleExpanded={() => {
            const next = expandedId === item.id ? null : item.id;
            setExpandedId(next);
            track(ANALYTICS_EVENTS.SCOUT_SUGGESTION_CLICKED, {
              suggestion_kind: item.kind,
              skill_name: item.skill_name,
              click_target: next === item.id ? "expand" : "collapse",
              surface,
            });
          }}
          onDismiss={() => void actions.dismiss(item)}
          onActivate={() => void actions.activate(item)}
        />
      ))}
    </div>
  );
}

function CollapsedLine({ titles }: { titles: string[] }) {
  if (titles.length === 0) {
    return (
      <span className="text-[12px] text-gray-10">
        Nothing left to suggest right now.
      </span>
    );
  }
  const named = titles.slice(0, COLLAPSED_TITLE_PREVIEW).join(", ");
  const rest = titles.length - COLLAPSED_TITLE_PREVIEW;
  return (
    <span className="truncate text-[12px] text-gray-11">
      {named}
      {rest > 0 ? ` and ${rest} more` : ""}
    </span>
  );
}

function SuggestionsSkeleton() {
  return (
    <div className="grid @2xl:grid-cols-2 @4xl:grid-cols-3 grid-cols-1 gap-2">
      {[0, 1, 2].map((index) => (
        <div
          key={index}
          className="flex flex-col gap-2 rounded-(--radius-3) border border-border bg-(--color-panel-solid) p-3"
        >
          <Skeleton className="h-3.5 w-16" />
          <Skeleton className="h-3.5 w-4/5" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-6 w-24" />
        </div>
      ))}
    </div>
  );
}
