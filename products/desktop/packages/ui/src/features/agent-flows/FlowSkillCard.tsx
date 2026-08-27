import { FlowArrowIcon } from "@phosphor-icons/react";
import { FlowStepChain } from "./flowChips";
import type { AgentFlowRecord } from "./useAgentFlows";

/** List row for a flow-skill on the Skills page; opens the flow editor. */
export function FlowSkillCard({
  flow,
  onClick,
}: {
  flow: AgentFlowRecord;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className="flex w-full cursor-pointer items-center gap-2 rounded-lg border border-gray-6 bg-gray-2 px-3 py-2 text-left transition-colors hover:border-gray-8 hover:bg-gray-3"
      onClick={onClick}
    >
      <span className="flex shrink-0 items-center justify-center rounded bg-violet-3 p-1.5 text-violet-11">
        <FlowArrowIcon size={14} weight="duotone" />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="truncate font-medium text-[13px] text-gray-12">
          {flow.name}
        </span>
        <FlowStepChain flow={flow} />
      </span>
      <span className="shrink-0 rounded-full border border-gray-5 px-1.5 py-0.5 text-[10px] text-gray-10">
        {flow.steps.length} steps
      </span>
    </button>
  );
}
