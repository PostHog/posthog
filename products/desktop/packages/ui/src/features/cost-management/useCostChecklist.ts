import {
  buildCostChecklist,
  type CostChecklistItem,
} from "@posthog/core/billing/costChecklist";
import { LEAN_SKILLS } from "@posthog/core/billing/leanSkills";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useSkills } from "@posthog/ui/features/skills/useSkills";
import { useMemo } from "react";

/**
 * The checklist for the signed-in user: their default model, the images their
 * cloud runs can start from, which lean skills they have, and what they have
 * acted on.
 */
export function useCostChecklist(): CostChecklistItem[] {
  const defaultModelId = useSettingsStore((state) => state.lastUsedModel);
  const completed = useSettingsStore((state) => state.costChecklistDone);
  const { images } = useSandboxCustomImages();
  const installed = useInstalledLeanSkills();

  // Only a ready image can be a session's base image, which is the same filter
  // the base-image pickers apply. A draft, scanning, building, failed, or
  // archived image cannot start a run, so the recommendation stands until a
  // build actually lands.
  const hasCustomImage = images.some((image) => image.status === "ready");

  return buildCostChecklist({
    defaultModelId,
    hasCustomImage,
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
  return useMemo(() => {
    const byId = new Map<string, string>();
    for (const skill of skills.data ?? []) {
      if (LEAN_SKILLS.some((lean) => lean.skillId === skill.name)) {
        byId.set(skill.name, skill.path);
      }
    }
    return byId;
  }, [skills.data]);
}
