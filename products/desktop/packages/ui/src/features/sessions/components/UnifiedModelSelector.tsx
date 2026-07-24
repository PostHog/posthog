import type {
  SessionConfigOption,
  SessionConfigSelectGroup,
} from "@agentclientprotocol/sdk";
import {
  ArrowsClockwise,
  CaretDown,
  Cpu,
  Robot,
  Spinner,
} from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import { gateRestrictedModelPick } from "@posthog/ui/features/billing/modelGate";
import { ModelRadioItem } from "@posthog/ui/features/sessions/components/ModelRadioItem";
import { flattenSelectOptions } from "@posthog/ui/features/sessions/sessionStore";
import { useRetainedConfigOption } from "@posthog/ui/features/sessions/useRetainedConfigOption";
import type { AgentAdapter } from "@posthog/ui/features/settings/settingsStore";
import { Fragment, useMemo, useRef, useState } from "react";

const ADAPTER_ICONS: Record<AgentAdapter, React.ReactNode> = {
  claude: <Robot size={14} weight="regular" />,
  codex: <Cpu size={14} weight="regular" />,
};

const ADAPTER_LABELS: Record<AgentAdapter, string> = {
  claude: "Claude Code",
  codex: "Codex",
};

function getOtherAdapter(adapter: AgentAdapter): AgentAdapter {
  return adapter === "claude" ? "codex" : "claude";
}

interface UnifiedModelSelectorProps {
  modelOption?: SessionConfigOption;
  adapter: AgentAdapter;
  onAdapterChange: (adapter: AgentAdapter) => void;
  onModelChange?: (model: string) => void;
  disabled?: boolean;
  isConnecting?: boolean;
}

export function UnifiedModelSelector({
  modelOption,
  adapter,
  onAdapterChange,
  onModelChange,
  disabled,
  isConnecting,
}: UnifiedModelSelectorProps) {
  const [open, setOpen] = useState(false);
  const pendingValueRef = useRef<string | null>(null);
  // Keep the last model on the trigger while the new harness's config loads, so
  // the trigger doesn't shrink to the "Model" fallback and jostle the toolbar
  // mid-switch. The radio group below still renders from the live option once
  // loading finishes.
  const displayOption = useRetainedConfigOption(modelOption);
  const selectOption =
    displayOption?.type === "select" ? displayOption : undefined;
  const options = selectOption
    ? flattenSelectOptions(selectOption.options)
    : [];
  const groupedOptions = useMemo(() => {
    if (!selectOption || selectOption.options.length === 0) return [];
    if ("group" in selectOption.options[0]) {
      return selectOption.options as SessionConfigSelectGroup[];
    }
    return [];
  }, [selectOption]);

  const currentValue = selectOption?.currentValue;
  const currentLabel =
    options.find((opt) => opt.value === currentValue)?.name ?? currentValue;

  const otherAdapter = getOtherAdapter(adapter);

  // Collapse to a bare loading button only while the menu is closed (initial
  // load). When the menu is open we keep it mounted and surface the loading
  // state inside the content instead — switching harness refetches the new
  // adapter's config, and unmounting here would dismiss the picker mid-switch
  // and force the user to reopen it just to choose a model.
  if (isConnecting && !open) {
    return (
      <Button type="button" variant="default" size="sm" disabled>
        <Spinner size={12} className="animate-spin" />
        Loading...
      </Button>
    );
  }

  return (
    <DropdownMenu
      open={open}
      onOpenChange={setOpen}
      onOpenChangeComplete={(isOpen) => {
        if (!isOpen && pendingValueRef.current !== null) {
          onModelChange?.(pendingValueRef.current);
          pendingValueRef.current = null;
        }
      }}
    >
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={disabled}
            aria-label="Model"
          >
            <span className="text-muted-foreground">
              {ADAPTER_ICONS[adapter]}
            </span>
            {currentLabel ?? "Model"}
            <CaretDown
              size={10}
              weight="bold"
              className="text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={6}
        className="min-w-[220px]"
      >
        <MenuLabel>{ADAPTER_LABELS[adapter]}</MenuLabel>
        {isConnecting ? (
          <div className="flex items-center gap-2 px-2 py-1.5 text-muted-foreground">
            <Spinner size={12} className="animate-spin" />
            Loading...
          </div>
        ) : (
          <DropdownMenuRadioGroup
            value={currentValue ?? ""}
            onValueChange={(value) => {
              // A plan-restricted model opens the upgrade gate instead of
              // becoming the selection.
              if (gateRestrictedModelPick(options, value)) {
                pendingValueRef.current = null;
                setOpen(false);
                return;
              }
              pendingValueRef.current = value;
              setOpen(false);
            }}
          >
            {groupedOptions.length > 0
              ? groupedOptions.map((group, index) => (
                  <Fragment key={group.group}>
                    {index > 0 && <DropdownMenuSeparator />}
                    <MenuLabel>{group.name}</MenuLabel>
                    {group.options.map((model) => (
                      <ModelRadioItem key={model.value} model={model} />
                    ))}
                  </Fragment>
                ))
              : options.map((model) => (
                  <ModelRadioItem key={model.value} model={model} />
                ))}
          </DropdownMenuRadioGroup>
        )}

        <DropdownMenuSeparator />

        <DropdownMenuItem
          closeOnClick={false}
          onClick={() => onAdapterChange(otherAdapter)}
        >
          <ArrowsClockwise size={12} weight="bold" />
          Switch to {ADAPTER_LABELS[otherAdapter]}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
