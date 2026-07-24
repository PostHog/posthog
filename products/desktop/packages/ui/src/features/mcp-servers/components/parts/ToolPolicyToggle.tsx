import { Check, Prohibit, Shield } from "@phosphor-icons/react";
import type { McpApprovalState } from "@posthog/api-client/posthog-client";
import { Tooltip } from "@radix-ui/themes";

interface ToolPolicyToggleProps {
  value: McpApprovalState;
  onChange: (value: McpApprovalState) => void;
  disabled?: boolean;
}

const OPTIONS: {
  id: McpApprovalState;
  label: string;
  hint: string;
  Icon: typeof Check;
}[] = [
  {
    id: "approved",
    label: "Approved",
    hint: "Always allow",
    Icon: Check,
  },
  {
    id: "needs_approval",
    label: "Requires approval",
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
}: ToolPolicyToggleProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Tool permission"
      className="inline-flex items-stretch overflow-hidden rounded-md border border-gray-5 bg-gray-2"
    >
      {OPTIONS.map((option, index) => {
        const active = value === option.id;
        const activeClass =
          option.id === "approved"
            ? "bg-green-9 text-white"
            : option.id === "needs_approval"
              ? "bg-amber-9 text-white"
              : "bg-red-9 text-white";
        return (
          <Tooltip key={option.id} content={`${option.label} — ${option.hint}`}>
            {/* biome-ignore lint/a11y/useSemanticElements: segmented radio group needs custom button styling */}
            <button
              type="button"
              role="radio"
              aria-checked={active}
              disabled={disabled}
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
