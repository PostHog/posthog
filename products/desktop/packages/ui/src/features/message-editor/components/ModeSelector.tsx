import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import { flattenSelectOptions } from "@posthog/ui/features/sessions/sessionStore";
import { useRetainedConfigOption } from "@posthog/ui/features/sessions/useRetainedConfigOption";
import { useRef, useState } from "react";

interface ModeSelectorProps {
  modeOption: SessionConfigOption | undefined;
  onChange: (value: string) => void;
  allowBypassPermissions: boolean;
  disabled?: boolean;
  /**
   * When provided, an "Autoresearch" toggle renders as the last item of the
   * menu (new-task composer only). It arms/disarms the autonomous iteration
   * loop; `active` drives its checkmark. Applied after the menu closes, like a
   * mode change, so the composer doesn't relayout under the closing menu.
   */
  autoresearch?: {
    active: boolean;
    onToggle: () => void;
  };
}

export function ModeSelector({
  modeOption,
  onChange,
  allowBypassPermissions,
  disabled,
  autoresearch,
}: ModeSelectorProps) {
  const [open, setOpen] = useState(false);
  const pendingValueRef = useRef<string | null>(null);
  // A toggle picked from the menu, applied after the menu closes (like a mode
  // change) so the composer doesn't relayout under the closing menu.
  const pendingToggleRef = useRef<(() => void) | null>(null);
  const displayOption = useRetainedConfigOption(modeOption);

  if (!displayOption || displayOption.type !== "select") return null;

  // `modeOption` blanks out while the preview config reloads (e.g. a harness
  // switch). Keep showing the last mode, disabled, so the toolbar stays put
  // instead of collapsing and snapping the open model menu sideways.
  const isReloading = !modeOption;
  const isDisabled = disabled || isReloading;

  const allOptions = flattenSelectOptions(displayOption.options);
  const options = allowBypassPermissions
    ? allOptions
    : allOptions.filter(
        (opt) =>
          opt.value !== "bypassPermissions" && opt.value !== "full-access",
      );
  if (options.length === 0) return null;

  const currentValue = displayOption.currentValue;
  const currentLabel =
    allOptions.find((opt) => opt.value === currentValue)?.name ?? currentValue;
  // Running unsupervised is the only mode the trigger colours at all, and it
  // does so as a whole destructive button rather than a tinted label — a mode
  // tint per mode turns the toolbar into a palette and stops reading as a
  // warning where it matters.
  const bypassActive =
    currentValue === "bypassPermissions" || currentValue === "full-access";

  const toggles: Array<{
    label: string;
    active: boolean;
    onToggle: () => void;
  }> = [];
  if (autoresearch) {
    toggles.push({ label: "Autoresearch", ...autoresearch });
  }

  return (
    <DropdownMenu
      open={open}
      onOpenChange={setOpen}
      onOpenChangeComplete={(isOpen) => {
        if (isOpen) return;
        if (pendingValueRef.current !== null) {
          onChange(pendingValueRef.current);
          pendingValueRef.current = null;
        }
        const pendingToggle = pendingToggleRef.current;
        pendingToggleRef.current = null;
        pendingToggle?.();
      }}
    >
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant={bypassActive ? "destructive" : "default"}
            size="sm"
            disabled={isDisabled}
            aria-label="Mode"
          >
            <span>{currentLabel}</span>
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={6}
        className={allowBypassPermissions ? "min-w-[220px]" : "min-w-[200px]"}
      >
        <MenuLabel>Mode</MenuLabel>
        <DropdownMenuRadioGroup
          value={currentValue}
          onValueChange={(value) => {
            pendingValueRef.current = value;
            setOpen(false);
          }}
        >
          {options.map((option) => (
            <DropdownMenuRadioItem key={option.value} value={option.value}>
              <span className="whitespace-nowrap">{option.name}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {toggles.length > 0 && <DropdownMenuSeparator />}
        {toggles.map((toggle) => (
          <DropdownMenuCheckboxItem
            key={toggle.label}
            checked={toggle.active}
            onCheckedChange={() => {
              pendingToggleRef.current = toggle.onToggle;
              setOpen(false);
            }}
          >
            <span className="whitespace-nowrap">{toggle.label}</span>
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
