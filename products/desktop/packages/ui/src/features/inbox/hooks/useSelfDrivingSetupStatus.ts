import { useSignalSourceConfigs } from "@posthog/ui/features/inbox/hooks/useSignalSourceConfigs";
import { useScoutConfigs } from "@posthog/ui/features/scouts/hooks/useScoutConfigs";

export interface SelfDrivingSetupStatus {
  isLoading: boolean;
  /** At least one signal source or scout is enabled. */
  isConfigured: boolean;
}

/**
 * Whether Self-driving has anything to watch yet. Mirrors the web inbox's
 * `isSelfDrivingSetUp` check (enabled sources + enabled scouts > 0), so the
 * two surfaces agree on when a project still needs the welcome takeover.
 */
export function useSelfDrivingSetupStatus(): SelfDrivingSetupStatus {
  const { data: sourceConfigs, isLoading: sourcesLoading } =
    useSignalSourceConfigs();
  const { data: scoutConfigs, isLoading: scoutsLoading } = useScoutConfigs();

  const enabledSourceCount =
    sourceConfigs?.filter((config) => config.enabled).length ?? 0;
  const enabledScoutCount =
    scoutConfigs?.filter((config) => config.enabled).length ?? 0;

  return {
    isLoading: sourcesLoading || scoutsLoading,
    isConfigured: enabledSourceCount + enabledScoutCount > 0,
  };
}
