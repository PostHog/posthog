import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { prettifyScoutSkillName } from "@posthog/core/scouts/scoutPresentation";
import { ScoutNameHoverCard } from "./ScoutNameHoverCard";

/** The agent's name, opening its page. Resting on it shows what the agent does. */
export function AgentNameLink({
  config,
  onOpen,
  dataAttr,
}: {
  config: ScoutConfig;
  onOpen: () => void;
  dataAttr?: string;
}) {
  return (
    <ScoutNameHoverCard
      config={config}
      trigger={
        <button
          type="button"
          onClick={onOpen}
          className="cursor-pointer truncate border-0 bg-transparent p-0 text-left font-medium text-[13px] text-gray-12 hover:underline"
          data-attr={dataAttr}
        >
          {prettifyScoutSkillName(config.skill_name)}
        </button>
      }
    />
  );
}
