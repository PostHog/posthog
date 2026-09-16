import { scoutDisplayName } from "@posthog/core/scouts/scoutPresentation";
import { useScoutConfigs } from "./useScoutConfigs";

/**
 * What to call a scout when all the caller holds is its skill name.
 *
 * The label lives on the config, so this reads the fleet query every scout surface already
 * shares. Falls back to a label derived from the slug while the fleet is loading, or for a
 * scout this project has no config for.
 */
export function useScoutDisplayName(skillName: string): string {
  const { data: configs } = useScoutConfigs();
  const config = configs?.find((entry) => entry.skill_name === skillName);
  return scoutDisplayName(config ?? { skill_name: skillName });
}
