import type { HomeExperiment, HomeWork } from "@posthog/core/home/homeSchemas";
import { Skeleton } from "@posthog/quill";
import { HomeExperiments } from "@posthog/ui/features/home/components/HomeExperiments";
import { HomeFlagSuggestions } from "@posthog/ui/features/home/components/HomeFlagSuggestions";
import { HomeHero } from "@posthog/ui/features/home/components/HomeHero";
import { HomeSection } from "@posthog/ui/features/home/components/HomeSection";
import type { HomeFlagSuggestion } from "@posthog/ui/features/home/homeSuggestions";
import type { ReactNode } from "react";

function count(n: number, singular: string, plural: string): string {
  return `${n} ${n === 1 ? singular : plural}`;
}

/** The line under the hero, counting what the page below actually holds. */
export function homeSubhead(counts: {
  suggestions: number;
  experiments: number;
  canvases: number;
}): string {
  const parts: string[] = [];
  if (counts.suggestions > 0) {
    parts.push(
      `${count(counts.suggestions, "feature flag", "feature flags")} to pick up`,
    );
  }
  if (counts.experiments > 0) {
    parts.push(
      `${count(counts.experiments, "experiment", "experiments")} in flight`,
    );
  }
  if (counts.canvases > 0) {
    parts.push(`${count(counts.canvases, "pinned canvas", "pinned canvases")}`);
  }
  if (parts.length === 0) {
    return "Start a space to give a piece of work its own place to happen.";
  }
  if (parts.length === 1) return `${parts[0]}, below.`;
  const last = parts[parts.length - 1];
  const rest = parts.slice(0, -1);
  // Serial comma only where there are three or more, so two parts read as a
  // sentence rather than a list.
  const separator = rest.length > 1 ? ", and " : " and ";
  return `${rest.join(", ")}${separator}${last}.`;
}

function SectionSkeleton() {
  return (
    <div className="flex flex-col gap-2 px-6 py-6">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-14 w-full" />
      <Skeleton className="h-14 w-full" />
    </div>
  );
}

function UnavailableNote({ groups }: { groups: HomeWork["unavailable"] }) {
  const names = groups.map((group) =>
    group === "experiments" ? "experiments" : "feature flags",
  );
  return (
    <p className="px-6 py-6 text-muted-foreground text-xs">
      Home couldn't load your {names.join(" or ")}. If this login doesn't have
      access to them, sign in again.
    </p>
  );
}

/**
 * Home's page body, given what to show. Everything it renders arrives as props
 * so the whole page can be seen in Storybook — the container above it
 * (`HomeView`) is the only part that knows how to fetch.
 */
export function HomePage({
  isLoading,
  orgName,
  logoSrc,
  suggestions,
  experiments,
  unavailable,
  canvasCount,
  canvasSections,
}: {
  isLoading: boolean;
  orgName: string | null;
  logoSrc?: string;
  suggestions: HomeFlagSuggestion[];
  experiments: HomeExperiment[];
  unavailable: HomeWork["unavailable"];
  /** How many canvases are stacked below, for the hero's line. */
  canvasCount: number;
  /** The stacked canvases themselves, each its own live surface. */
  canvasSections: ReactNode;
}) {
  const subhead = isLoading
    ? "Loading your work…"
    : homeSubhead({
        suggestions: suggestions.length,
        experiments: experiments.length,
        canvases: canvasCount,
      });

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col divide-y divide-border pb-16">
        <HomeHero orgName={orgName} logoSrc={logoSrc} subhead={subhead} />

        {isLoading ? (
          <SectionSkeleton />
        ) : (
          <>
            {suggestions.length > 0 && (
              <HomeSection
                title="Suggestions"
                description="Recent feature flags. Give one a space and the work behind it has somewhere to happen."
              >
                <HomeFlagSuggestions suggestions={suggestions} />
              </HomeSection>
            )}

            {experiments.length > 0 && (
              <HomeSection
                title="Experiments"
                description="What is running, and how long it has been running for."
              >
                <HomeExperiments experiments={experiments} />
              </HomeSection>
            )}

            {canvasSections}

            {unavailable.length > 0 && <UnavailableNote groups={unavailable} />}
          </>
        )}
      </div>
    </div>
  );
}
