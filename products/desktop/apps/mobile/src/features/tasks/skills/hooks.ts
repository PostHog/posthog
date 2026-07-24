import { useQuery } from "@tanstack/react-query";
import { getSkillStoreSkill, getSkillStoreSkills } from "./api";

const skillStoreKeys = {
  all: ["skill-store"] as const,
  lists: () => [...skillStoreKeys.all, "list"] as const,
  list: () => [...skillStoreKeys.lists(), "all"] as const,
  details: () => [...skillStoreKeys.all, "detail"] as const,
  detail: (skillName: string) =>
    [...skillStoreKeys.details(), skillName] as const,
};

export function useSkillStoreSkills() {
  return useQuery({
    queryKey: skillStoreKeys.list(),
    queryFn: getSkillStoreSkills,
    staleTime: 5 * 60 * 1000,
  });
}

export function useSkillStoreSkill(skillName: string | null) {
  return useQuery({
    queryKey: skillStoreKeys.detail(skillName ?? ""),
    queryFn: () => getSkillStoreSkill(skillName as string),
    enabled: !!skillName,
    staleTime: 5 * 60 * 1000,
  });
}

export const SKILL_STORE_QUERY_KEYS = skillStoreKeys;
