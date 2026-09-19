import { scoutNameForSkill } from "@posthog/core/scouts/scoutPresentation";
import { useScoutConfigs } from "./useScoutConfigs";

/**
 * The name a scout goes by, read from the fleet cache the list and detail
 * pages already fill.
 */
export function useScoutName(skillName: string): string {
  const { data: configs } = useScoutConfigs();
  return scoutNameForSkill(configs, skillName);
}
