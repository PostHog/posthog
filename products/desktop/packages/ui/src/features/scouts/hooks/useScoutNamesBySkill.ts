import { scoutNamesBySkill } from "@posthog/shared/scout-names";
import { useMemo } from "react";
import { useScoutConfigs } from "./useScoutConfigs";

/** Each scout's display name, keyed by skill name. Resolve through
 * `scoutNameForSkill`, which covers scouts with no config. */
export function useScoutNamesBySkill(): Record<string, string> {
  const { data: configs } = useScoutConfigs();
  return useMemo(() => scoutNamesBySkill(configs), [configs]);
}
