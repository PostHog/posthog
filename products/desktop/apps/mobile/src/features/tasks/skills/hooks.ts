import { useQuery } from "@tanstack/react-query";
import { getPostHogApiClient } from "@/lib/posthogApiClient";

const skillStoreKeys = {
  all: ["skill-store"] as const,
  lists: () => [...skillStoreKeys.all, "list"] as const,
  list: () => [...skillStoreKeys.lists(), "all"] as const,
  details: () => [...skillStoreKeys.all, "detail"] as const,
  detail: (skillName: string) =>
    [...skillStoreKeys.details(), skillName] as const,
  files: () => [...skillStoreKeys.all, "file"] as const,
  file: (skillName: string, path: string) =>
    [...skillStoreKeys.files(), skillName, path] as const,
};

/**
 * Team skills. `data` is `null` — not `[]` — when the API answers 403, which is
 * how a project without the skills feature reads; callers that need to hide a
 * surface entirely must branch on that instead of on emptiness.
 */
export function useSkillStoreSkills() {
  return useQuery({
    queryKey: skillStoreKeys.list(),
    queryFn: () => getPostHogApiClient().listLlmSkills(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useSkillStoreSkill(skillName: string | null) {
  return useQuery({
    queryKey: skillStoreKeys.detail(skillName ?? ""),
    queryFn: () => getPostHogApiClient().getLlmSkillByName(skillName as string),
    enabled: !!skillName,
    staleTime: 5 * 60 * 1000,
  });
}

/** Reads one companion file's contents; the skill detail only lists paths. */
export function useSkillStoreSkillFile(
  skillName: string | null,
  path: string | null,
) {
  return useQuery({
    queryKey: skillStoreKeys.file(skillName ?? "", path ?? ""),
    queryFn: () =>
      getPostHogApiClient().getLlmSkillFile(
        skillName as string,
        path as string,
      ),
    enabled: !!skillName && !!path,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Whether the skills surfaces should exist at all for this project. Undefined
 * while unresolved, so navigation can stay hidden until we know rather than
 * flashing an entry that 403s on tap.
 */
export function useSkillsAvailable(): boolean | undefined {
  const { data, isPending, isError } = useSkillStoreSkills();
  if (isPending) return undefined;
  if (isError) return undefined;
  return data !== null;
}

export const SKILL_STORE_QUERY_KEYS = skillStoreKeys;
