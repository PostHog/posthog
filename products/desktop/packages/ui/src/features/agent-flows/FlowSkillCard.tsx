import { FlowArrowIcon } from "@phosphor-icons/react";
import { SkillListCard } from "@posthog/ui/features/skills/SkillListCard";
import { SkillChip } from "@posthog/ui/features/skills/SkillPanelHeader";
import type { AgentFlowRecord } from "./useAgentFlows";

export function FlowSkillCard({
  flow,
  isSelected,
  onClick,
}: {
  flow: AgentFlowRecord;
  isSelected: boolean;
  onClick: () => void;
}) {
  const models = new Set(flow.steps.map((step) => step.model.name));
  return (
    <SkillListCard
      icon={<FlowArrowIcon size={12} weight="duotone" />}
      iconClass="bg-violet-3 text-violet-11"
      title={flow.name}
      subtitle={flow.steps.map((step) => step.name).join(" → ")}
      isSelected={isSelected}
      onClick={onClick}
      trailing={
        <SkillChip>
          {models.size === 1 ? [...models][0] : `${flow.steps.length} steps`}
        </SkillChip>
      }
    />
  );
}
