import { CaretDown } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@posthog/quill";

interface SettingsOptionSelectOption {
  value: string;
  label: string;
}

interface SettingsOptionSelectProps {
  value: string;
  options: SettingsOptionSelectOption[];
  onValueChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel: string;
  placeholder?: string;
  className?: string;
  size?: "sm" | "default" | "lg";
}

export function SettingsOptionSelect({
  value,
  options,
  onValueChange,
  disabled,
  ariaLabel,
  placeholder = "Select…",
  className,
  size = "sm",
}: SettingsOptionSelectProps) {
  const selectedLabel =
    options.find((opt) => opt.value === value)?.label ?? placeholder;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size={size}
            disabled={disabled}
            aria-label={ariaLabel}
            className={`w-full justify-between ${
              size === "sm" ? "" : "text-[13px]"
            } ${className ?? ""}`}
          >
            <span className="min-w-0 truncate">{selectedLabel}</span>
            <CaretDown
              size={10}
              weight="bold"
              className="shrink-0 text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="bottom"
        sideOffset={6}
        className="min-w-(--anchor-width)"
      >
        <DropdownMenuRadioGroup value={value} onValueChange={onValueChange}>
          {options.map((opt) => (
            <DropdownMenuRadioItem key={opt.value} value={opt.value}>
              {opt.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
