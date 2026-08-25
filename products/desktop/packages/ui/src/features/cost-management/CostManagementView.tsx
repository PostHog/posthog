import type { CostChecklistItem } from "@posthog/core/billing/costChecklist";
import { ContextCompactionSettings } from "@posthog/ui/features/cost-management/ContextCompactionSettings";
import { CostChecklistPanel } from "@posthog/ui/features/cost-management/CostChecklistPanel";
import { SettingsSubsection } from "@posthog/ui/features/settings/components/SettingsSubsection";
import { SpendLimitsSettings } from "@posthog/ui/features/settings/sections/SpendLimitsSettings";

interface CostManagementViewProps {
  items: CostChecklistItem[];
  onSwitchModel: (toModelId: string) => void;
  onCreateImage: () => void;
  onInstallSkill: (skillId: string) => void;
  onUninstallSkill: (skillId: string) => void;
  onOpenSkill: (skillId: string) => void;
  busySkillIds: ReadonlySet<string>;
}

export function CostManagementView({
  items,
  onSwitchModel,
  onCreateImage,
  onInstallSkill,
  onUninstallSkill,
  onOpenSkill,
  busySkillIds,
}: CostManagementViewProps) {
  return (
    <div className="flex flex-col gap-8">
      <SpendLimitsSettings />
      <ContextCompactionSettings />
      <SettingsSubsection
        title="Recommendations"
        description="Ways to spend less on your runs. Each button makes the change, and done items stay checked below."
      >
        <CostChecklistPanel
          items={items}
          onSwitchModel={onSwitchModel}
          onCreateImage={onCreateImage}
          onInstallSkill={onInstallSkill}
          onUninstallSkill={onUninstallSkill}
          onOpenSkill={onOpenSkill}
          busySkillIds={busySkillIds}
        />
      </SettingsSubsection>
    </div>
  );
}
