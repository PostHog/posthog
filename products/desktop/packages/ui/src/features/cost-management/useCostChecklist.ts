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
  const { images, customImagesEnabled, customImagesDisabled } =
    useSandboxCustomImages();
  const skills = useSkills();
  const installed = useInstalledLeanSkills();

  // Custom images are usable only when the feature is on, its list has loaded,
  // and the org has not disabled it — the same signal the base-image pickers
  // use. Until then hasCustomImage is null so no row is shown, rather than a
  // permanent build suggestion the user cannot act on. Once usable, only a
  // ready image checks the row off, matching the pickers' ready filter.
  const customImagesReady = customImagesEnabled && !customImagesDisabled;
  const hasCustomImage = customImagesReady
    ? images.some((image) => image.status === "ready")
    : null;

  // Wait for the installed-skills list before deriving skill rows; an empty
  // list before it loads would mislabel installed skills as installable and
  // invite a duplicate install that fails.
  const skillsLoaded = skills.data !== undefined;

  return buildCostChecklist({
    defaultModelId,
    hasCustomImage,
    skills: skillsLoaded
      ? LEAN_SKILLS.map((skill) => ({
          skillId: skill.skillId,
          name: skill.name,
          installed: installed.has(skill.skillId),
        }))
      : [],
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
