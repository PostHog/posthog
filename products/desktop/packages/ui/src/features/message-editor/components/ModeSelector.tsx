import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { CaretDown, ChartLineUp, Shapes } from "@phosphor-icons/react";
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
import { getModeStyle } from "@posthog/ui/features/sessions/modeStyles";
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
  /**
   * When provided, a "Canvas" toggle renders in the same trailing section
   * (channels composer only). Arming it makes the next submit generate a
   * canvas from the prompt instead of creating a plain task; while armed the
   * trigger reads "Canvas" so the composer's state is visible at a glance.
   */
  canvas?: {
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
  canvas,
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
  const canvasActive = !!canvas?.active;
  const currentStyle = canvasActive
    ? { icon: <Shapes size={12} weight="fill" />, className: "text-teal-11" }
    : getModeStyle(currentValue);
  const currentLabel = canvasActive
    ? "Canvas"
    : (allOptions.find((opt) => opt.value === currentValue)?.name ??
      currentValue);

  const toggles: Array<{
    label: string;
    active: boolean;
    onToggle: () => void;
    icon: React.ReactNode;
    className: string;
  }> = [];
  if (canvas) {
    toggles.push({
      label: "Canvas",
      ...canvas,
      icon: <Shapes size={12} weight="fill" />,
      className: "text-teal-11",
    });
  }
  if (autoresearch) {
    toggles.push({
      label: "Autoresearch",
      ...autoresearch,
      icon: <ChartLineUp size={12} />,
      className: "text-muted-foreground",
    });
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
          // Picking a plain mode leaves canvas mode; the two are exclusive.
          if (canvasActive) canvas?.onToggle();
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
            variant="default"
            size="sm"
            disabled={isDisabled}
            aria-label="Mode"
          >
            <span className={currentStyle.className}>{currentStyle.icon}</span>
            <span className={currentStyle.className}>{currentLabel}</span>
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
        className={allowBypassPermissions ? "min-w-[220px]" : "min-w-[200px]"}
      >
        <MenuLabel>Mode</MenuLabel>
        <DropdownMenuRadioGroup
          // While canvas mode is armed it reads as the selected mode, so no
          // plain-mode radio shows checked.
          value={canvasActive ? "" : currentValue}
          onValueChange={(value) => {
            pendingValueRef.current = value;
            setOpen(false);
          }}
        >
          {options.map((option) => {
            const style = getModeStyle(option.value);
            return (
              <DropdownMenuRadioItem key={option.value} value={option.value}>
                <span className={`${style.className}`}>{style.icon}</span>
                <span className="whitespace-nowrap">{option.name}</span>
              </DropdownMenuRadioItem>
            );
          })}
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
            <span className={toggle.className}>{toggle.icon}</span>
            <span className="whitespace-nowrap">{toggle.label}</span>
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
