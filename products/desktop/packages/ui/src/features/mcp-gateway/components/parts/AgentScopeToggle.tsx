import type { McpAgentGrantScope } from "@posthog/api-client/posthog-client";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";

const OPTIONS: { id: McpAgentGrantScope; label: string; hint: string }[] = [
  {
    id: "personal",
    label: "Just my agents",
    hint: "The agent uses your connection only when it runs for you.",
  },
  {
    id: "team",
    label: "All team agents",
    hint: "The agent uses your connection for every run in this project, including runs nobody started. Teammates can't use the connection directly, but agents act through it on their runs too.",
  },
];

/**
 * Reach of the caller's own agent share: their runs only, or every run of
 * the agent in the project. Shown only on shares the caller owns.
 */
export function AgentScopeToggle({
  value,
  disabled,
  onChange,
}: {
  value: McpAgentGrantScope;
  disabled?: boolean;
  onChange: (scope: McpAgentGrantScope) => void;
}) {
  return (
    <TooltipProvider>
      <div
        role="radiogroup"
        aria-label="Which runs use your connection"
        className="inline-flex items-stretch overflow-hidden rounded-md border border-gray-5 bg-gray-2"
      >
        {OPTIONS.map((option, index) => {
          const active = value === option.id;
          return (
            <Tooltip key={option.id}>
              <TooltipTrigger
                render={
                  // biome-ignore lint/a11y/useSemanticElements: segmented radio group needs custom button styling
                  <button
                    type="button"
                    role="radio"
                    aria-checked={active}
                    disabled={disabled}
                    onClick={() => {
                      if (!active) onChange(option.id);
                    }}
                    className={`whitespace-nowrap px-2 py-1 text-xs transition-colors disabled:opacity-50 ${
                      index > 0 ? "border-gray-5 border-l" : ""
                    } ${
                      active
                        ? "bg-accent-4 font-medium text-accent-11"
                        : "text-gray-11 hover:bg-gray-3"
                    }`}
                  >
                    {option.label}
                  </button>
                }
              />
              <TooltipContent className="max-w-[280px]">
                {option.hint}
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </TooltipProvider>
  );
}
