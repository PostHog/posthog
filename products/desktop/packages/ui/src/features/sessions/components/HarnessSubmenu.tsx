import {
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@posthog/quill";
import type { AgentAdapter } from "@posthog/ui/features/settings/settingsStore";

export type AgentHarness = AgentAdapter | "pi";

const harnessLabels: Record<AgentHarness, string> = {
  claude: "Claude Code",
  codex: "Codex",
  pi: "Pi",
};

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
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <span>Harness</span>
        <span className="flex-1 text-right text-muted-foreground">
          {harnessLabels[value]}
        </span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(nextHarness) => {
            if (
              nextHarness === "claude" ||
              nextHarness === "codex" ||
              (includePi && nextHarness === "pi")
            ) {
              onChange(nextHarness);
            }
          }}
        >
          <DropdownMenuRadioItem value="claude" closeOnClick={closeOnChange}>
            Claude Code
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="codex" closeOnClick={closeOnChange}>
            Codex
          </DropdownMenuRadioItem>
          {includePi && (
            <DropdownMenuRadioItem value="pi" closeOnClick={closeOnChange}>
              Pi
            </DropdownMenuRadioItem>
          )}
        </DropdownMenuRadioGroup>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
