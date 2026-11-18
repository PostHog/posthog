import {
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@posthog/quill";
import { RUNTIME_OPTIONS } from "@posthog/shared/model-catalog";
import type { AgentAdapter } from "@posthog/ui/features/settings/settingsStore";

export type AgentHarness = AgentAdapter | "pi";

const harnessOptions = RUNTIME_OPTIONS.map((option) => ({
  value: (option.runtimeAdapter ?? option.runtime) as AgentHarness,
  label: option.label,
}));

interface HarnessSubmenuProps {
  value: AgentHarness;
  includePi?: boolean;
  closeOnChange?: boolean;
  onChange: (harness: AgentHarness) => void;
}

export function HarnessSubmenu({
  value,
  includePi,
  closeOnChange = true,
  onChange,
}: HarnessSubmenuProps): React.JSX.Element {
  const options = includePi
    ? harnessOptions
    : harnessOptions.filter((option) => option.value !== "pi");

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <span>Harness</span>
        <span className="flex-1 text-right text-muted-foreground">
          {harnessOptions.find((option) => option.value === value)?.label}
        </span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(nextHarness) => {
            const picked = options.find(
              (option) => option.value === nextHarness,
            );
            if (picked) {
              onChange(picked.value);
            }
          }}
        >
          {options.map((option) => (
            <DropdownMenuRadioItem
              key={option.value}
              value={option.value}
              closeOnClick={closeOnChange}
            >
              {option.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
