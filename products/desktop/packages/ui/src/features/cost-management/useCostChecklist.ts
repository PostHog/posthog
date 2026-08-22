import {
  buildCostChecklist,
  type CostChecklistItem,
} from "@posthog/core/billing/costChecklist";
import { LEAN_SKILLS } from "@posthog/core/billing/leanSkills";
import { useSpendTotals } from "@posthog/ui/features/billing/useSpendTotals";
import { useSandboxEnvironments } from "@posthog/ui/features/settings/sections/environments/useSandboxEnvironments";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useSkills } from "@posthog/ui/features/skills/useSkills";

/**
 * The checklist for the signed-in user: their default model, the repository
 * their cloud runs use, which lean skills they have, and what they have acted
 * on.
 */
export function useCostChecklist(): CostChecklistItem[] {
  const defaultModelId = useSettingsStore((state) => state.lastUsedModel);
  const cloudRepository = useSettingsStore(
    (state) => state.lastUsedCloudRepository,
  );
  const completed = useSettingsStore((state) => state.costChecklistDone);
  const { environments } = useSandboxEnvironments();
  const installed = useInstalledLeanSkills();
  const totals = useSpendTotals();

  const repository = cloudRepository?.toLowerCase() ?? null;
  const cloudRepositoryHasCustomImage = (environments ?? []).some(
    (environment) =>
      environment.custom_image_id !== null &&
      environment.repositories.some(
        (repo) => repo.toLowerCase() === repository,
      ),
  );

  return buildCostChecklist({
    defaultModelId,
    cloudRepository,
    cloudRepositoryHasCustomImage,
    hasSpendHistory: (totals?.avgDailyUsd ?? 0) > 0,
    skills: LEAN_SKILLS.map((skill) => ({
      skillId: skill.skillId,
      name: skill.name,
      installed: installed.has(skill.skillId),
    })),
    completed,
  });
}

/**
 * Lean skills present locally, mapped to the path they live at so one can be
 * removed from the same place it was added.
 */
export function useInstalledLeanSkills(): Map<string, string> {
  const skills = useSkills();
  const byId = new Map<string, string>();
  for (const skill of skills.data ?? []) {
    if (LEAN_SKILLS.some((lean) => lean.skillId === skill.name)) {
      byId.set(skill.name, skill.path);
    }
  }
  return byId;
}
