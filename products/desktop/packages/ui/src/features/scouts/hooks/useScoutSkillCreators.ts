import {
  buildScoutCreatorIndex,
  type ScoutCreatorIndex,
} from "@posthog/core/scouts/scoutPresentation";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../../auth/store";
import { scoutQueryKeys } from "./scoutQueryKeys";

/**
 * Skill name → author of each scout's backing skill, for creator filtering.
 * Resolves to null when the org lacks the team-skills feature — callers should
 * drop creator affordances entirely rather than show an always-empty filter.
 */
export function useScoutSkillCreators() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  return useAuthenticatedQuery<ScoutCreatorIndex | null>(
    scoutQueryKeys.skillCreators(projectId),
    async (client) => {
      const skills = await client.listLlmSkills({ category: "scout" });
      return skills === null ? null : buildScoutCreatorIndex(skills);
    },
    { enabled: !!projectId, staleTime: 30_000 },
  );
}
