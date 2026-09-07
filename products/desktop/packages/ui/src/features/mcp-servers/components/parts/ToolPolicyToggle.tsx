import { Check, Prohibit, Shield } from "@phosphor-icons/react";
import type { McpApprovalState } from "@posthog/api-client/posthog-client";
import { Tooltip } from "@radix-ui/themes";

interface ToolPolicyToggleProps {
  value: McpApprovalState;
  onChange: (value: McpApprovalState) => void;
  disabled?: boolean;
  disabledStates?: Partial<Record<McpApprovalState, string>>;
  allowedStates?: readonly McpApprovalState[];
}

const OPTIONS: {
  id: McpApprovalState;
  label: string;
  hint: string;
  Icon: typeof Check;
}[] = [
  {
    id: "approved",
    label: "Always Allow",
    hint: "Run without asking",
    Icon: Check,
  },
  {
    id: "needs_approval",
    label: "Needs Approval",
    hint: "Ask every time",
    Icon: Shield,
  },
  {
    id: "do_not_use",
    label: "Blocked",
    hint: "Never allow",
    Icon: Prohibit,
  },
];

export function ToolPolicyToggle({
  value,
  onChange,
  disabled,
  disabledStates,
  allowedStates,
}: ToolPolicyToggleProps) {
  const visibleOptions = allowedStates
    ? OPTIONS.filter((option) => allowedStates.includes(option.id))
    : OPTIONS;

  return (
    <div
      role="radiogroup"
      aria-label="Tool permission"
      className="inline-flex items-stretch overflow-hidden rounded-md border border-gray-5 bg-gray-2"
    >
      {visibleOptions.map((option, index) => {
        const active = value === option.id;
        const disabledReason = disabledStates?.[option.id];
        const activeClass =
          option.id === "approved"
            ? "bg-green-9 text-white"
            : option.id === "needs_approval"
              ? "bg-amber-9 text-white"
              : "bg-red-9 text-white";
        return (
          <Tooltip
            key={option.id}
            content={disabledReason ?? `${option.label} — ${option.hint}`}
          >
            {/* biome-ignore lint/a11y/useSemanticElements: segmented radio group needs custom button styling */}
            <button
              type="button"
              role="radio"
              aria-checked={active}
              aria-label={option.label}
              disabled={disabled || !!disabledReason}
              onClick={() => onChange(option.id)}
              className={`flex items-center justify-center px-2.5 py-1.5 text-xs transition-colors disabled:opacity-50 ${
                index > 0 ? "border-gray-5 border-l" : ""
              } ${active ? activeClass : "text-gray-11 hover:bg-gray-3"}`}
            >
              <option.Icon size={12} weight="bold" />
            </button>
          </Tooltip>
        );
      })}
    </div>
  );
}
