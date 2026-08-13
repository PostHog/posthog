import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { HomeCanvasSection } from "@posthog/ui/features/home/components/HomeCanvasSection";
import { HomePage } from "@posthog/ui/features/home/components/HomePage";
import { homeFlagSuggestions } from "@posthog/ui/features/home/homeSuggestions";
import { useHomeCanvases } from "@posthog/ui/features/home/useHomeCanvases";
import { useHomeOrg } from "@posthog/ui/features/home/useHomeOrg";
import { useHomeWork } from "@posthog/ui/features/home/useHomeWork";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useMemo, useRef } from "react";

/**
 * Home: the page the app opens on, stacked out of the work already waiting in
 * PostHog. Its own sections come first, then the canvases pinned in your
 * personal space — each a live canvas, laid one under the next so the column
 * reads as one page.
 *
 * Every group loads up front rather than on scroll: Home exists to save the
 * trip to find the work, which a page that fetches as you reach it undoes.
 */
export function HomeView() {
  const { work, isLoading: workLoading } = useHomeWork();
  const { channels } = useChannels();
  const { canvases, isLoading: canvasesLoading } = useHomeCanvases();
  const { orgName, logoSrc } = useHomeOrg();

  const suggestions = useMemo(
    () => homeFlagSuggestions({ flags: work.featureFlags, channels }),
    [work.featureFlags, channels],
  );

  const isLoading = workLoading || canvasesLoading;
  // One view event per visit, once the page knows what it has — reporting at
  // mount would record every Home as empty.
  const reported = useRef(false);
  useEffect(() => {
    if (isLoading || reported.current) return;
    reported.current = true;
    track(ANALYTICS_EVENTS.HOME_VIEWED, {
      feature_flag_count: work.featureFlags.length,
      experiment_count: work.experiments.length,
      canvas_count: canvases.length,
      unavailable: work.unavailable,
    });
  }, [isLoading, work, canvases.length]);

  return (
    <HomePage
      isLoading={isLoading}
      orgName={orgName}
      logoSrc={logoSrc}
      suggestions={suggestions}
      experiments={work.experiments}
      unavailable={work.unavailable}
      canvasCount={canvases.length}
      canvasSections={canvases.map((canvas) => (
        <HomeCanvasSection key={canvas.id} canvas={canvas} />
      ))}
    />
  );
}
