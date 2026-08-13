import { cn, ToggleGroup, ToggleGroupItem } from "@posthog/quill";
import type { ReactNode } from "react";

export interface SettingsSegmentedOption {
  value: string;
  label: ReactNode;
}

interface SettingsSegmentedProps {
  value: string;
  options: SettingsSegmentedOption[];
  onValueChange: (value: string) => void;
  ariaLabel: string;
  disabled?: boolean;
  className?: string;
}

/**
 * Single-select segmented control for settings with two or three options,
 * so the choices read at a glance instead of hiding behind a dropdown.
 */
export function SettingsSegmented({
  value,
  options,
  onValueChange,
  ariaLabel,
  disabled,
  className,
}: SettingsSegmentedProps) {
  return (
    <ToggleGroup
      value={[value]}
      onValueChange={(next: string[]) => {
        const selected = next[0];
        if (selected && selected !== value) onValueChange(selected);
      }}
      aria-label={ariaLabel}
      disabled={disabled}
      className={cn("gap-1", className)}
    >
      {options.map((option) => (
        <ToggleGroupItem
          key={option.value}
          value={option.value}
          size="sm"
          variant="outline"
          disabled={disabled}
          className="h-6 px-2.5 text-[12px] text-gray-11 data-[pressed]:border-(--accent-9) data-[pressed]:bg-(--accent-3) data-[pressed]:text-(--accent-11)"
        >
          {option.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}
