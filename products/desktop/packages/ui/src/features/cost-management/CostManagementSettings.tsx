import { Gauge } from "@phosphor-icons/react";
import {
  imagePresetBrief,
  imagePresetName,
} from "@posthog/core/billing/imagePreset";
import {
  buildImageSpec,
  imageSpecToYaml,
} from "@posthog/core/billing/imageSpec";
import { leanSkillById } from "@posthog/core/billing/leanSkills";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { formatModelId } from "@posthog/shared";
import { CostManagementView } from "@posthog/ui/features/cost-management/CostManagementView";
import {
  type CustomImagePlan,
  CustomImageWizard,
} from "@posthog/ui/features/cost-management/CustomImageWizard";
import { LeanSkillDialog } from "@posthog/ui/features/cost-management/LeanSkillDialog";
import {
  useCostChecklist,
  useInstalledLeanSkills,
} from "@posthog/ui/features/cost-management/useCostChecklist";
import { useHandleOpenTask } from "@posthog/ui/features/deep-links/useHandleOpenTask";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useSandboxCustomImages } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useInstallMarketplaceSkill } from "@posthog/ui/features/skills/useMarketplace";
import { useDeleteSkill } from "@posthog/ui/features/skills/useSkillMutations";
import { useSpendAnalysisEnabled } from "@posthog/ui/features/usage/useSpendAnalysisEnabled";
import { toast } from "@posthog/ui/primitives/toast";
import { useState } from "react";

export function CostManagementSettings() {
  const spendAnalysisEnabled = useSpendAnalysisEnabled();
  const setLastUsedModel = useSettingsStore((state) => state.setLastUsedModel);
  const markDone = useSettingsStore((state) => state.markCostChecklistDone);
  const items = useCostChecklist();
  const installedSkills = useInstalledLeanSkills();
  const { createMutation, buildMutation } = useSandboxCustomImages();
  const installSkill = useInstallMarketplaceSkill();
  const deleteSkill = useDeleteSkill();
  const handleOpenTask = useHandleOpenTask();
  const [presetRepository, setPresetRepository] = useState<string | null>(null);
  const [openSkillId, setOpenSkillId] = useState<string | null>(null);
  const [busySkillId, setBusySkillId] = useState<string | null>(null);
  const openSkill = openSkillId === null ? null : leanSkillById(openSkillId);

  if (!spendAnalysisEnabled) {
    return (
      <Empty className="mx-auto max-w-md py-16">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Gauge size={24} />
          </EmptyMedia>
          <EmptyTitle>Cost management isn't available</EmptyTitle>
          <EmptyDescription>
            Spend reporting isn't enabled for your account yet, so there is
            nothing to set limits against.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const switchDefaultModel = (toModelId: string) => {
    const previous = useSettingsStore.getState().lastUsedModel;
    setLastUsedModel(toModelId);
    markDone("model-notch");
    toast.success(`New sessions start on ${formatModelId(toModelId)}`, {
      description: "Sessions already open keep the model they are on.",
      action: previous
        ? {
            label: "Undo",
            onClick: () => setLastUsedModel(previous),
          }
        : undefined,
    });
  };

  const createImage = async (plan: CustomImagePlan) => {
    const image = await createMutation.mutateAsync({
      name: imagePresetName(plan.repository ?? "cloud runs"),
      description: imagePresetBrief(
        plan.repository,
        plan.tools,
        plan.setupCommands,
      ),
      ...(plan.repository ? { repository: plan.repository } : {}),
    });
    setPresetRepository(null);
    markDone("custom-image");
    if (plan.mode === "build") {
      const spec = buildImageSpec(plan);
      await buildMutation.mutateAsync({
        id: image.id,
        specYaml: imageSpecToYaml(spec),
      });
      toast.success("Building your image", {
        description: "It scans first, then builds. This takes a few minutes.",
      });
      return;
    }
    // Creating an image always starts a builder session; open it so the plan
    // can be worked out in conversation.
    if (image.builder_task_id) void handleOpenTask(image.builder_task_id);
  };

  const installById = async (skillId: string) => {
    const skill = leanSkillById(skillId);
    if (!skill) return;
    setBusySkillId(skillId);
    try {
      await installSkill.mutateAsync({
        source: skill.source,
        skillId: skill.skillId,
      });
      toast.success(`${skill.name} installed`, {
        description: "New sessions pick it up. Manage it under Skills.",
        action: { label: "Open skills", onClick: () => openSettings("skills") },
      });
    } finally {
      setBusySkillId(null);
    }
  };

  const uninstallById = async (skillId: string) => {
    const skill = leanSkillById(skillId);
    const skillPath = installedSkills.get(skillId);
    if (!skill || !skillPath) return;
    setBusySkillId(skillId);
    try {
      await deleteSkill.mutateAsync({ skillPath });
      toast.success(`${skill.name} removed`, {
        description: "New sessions start without it.",
      });
    } finally {
      setBusySkillId(null);
    }
  };

  return (
    <>
      <CostManagementView
        items={items}
        creatingImage={createMutation.isPending}
        installingSkill={busySkillId !== null}
        onSwitchModel={switchDefaultModel}
        onCreateImage={setPresetRepository}
        onInstallSkill={(skillId) => void installById(skillId)}
        onUninstallSkill={(skillId) => void uninstallById(skillId)}
        onOpenSkill={setOpenSkillId}
        busySkillId={busySkillId}
      />
      {openSkill && (
        <LeanSkillDialog
          skill={openSkill}
          installed={installedSkills.has(openSkill.skillId)}
          busy={busySkillId === openSkill.skillId}
          onInstall={() => void installById(openSkill.skillId)}
          onUninstall={() => void uninstallById(openSkill.skillId)}
          onClose={() => setOpenSkillId(null)}
        />
      )}
      {presetRepository !== null && (
        <CustomImageWizard
          open
          defaultRepository={presetRepository}
          host="github"
          creating={createMutation.isPending || buildMutation.isPending}
          onCreate={(plan) => void createImage(plan)}
          onCancel={() => setPresetRepository(null)}
        />
      )}
    </>
  );
}
