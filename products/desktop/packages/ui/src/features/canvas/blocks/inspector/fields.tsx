import {
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import { settingsToggleItemClassName } from "@posthog/ui/features/settings/components/SettingsSegmented";
import { type ReactNode, useEffect, useId, useState } from "react";

export type MathValue = "total" | "dau" | "weekly_active" | "monthly_active";

const MATH_OPTIONS: Array<{ value: MathValue; label: string }> = [
  { value: "total", label: "Total count" },
  { value: "dau", label: "Unique users" },
  { value: "weekly_active", label: "Weekly active users" },
  { value: "monthly_active", label: "Monthly active users" },
];

function mathLabel(value: MathValue): string {
  return MATH_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function InspectorField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="font-medium text-[11px] text-muted-foreground">
        {label}
      </div>
      {children}
      {hint ? (
        <div className="text-[11px] text-muted-foreground/80 leading-snug">
          {hint}
        </div>
      ) : null}
    </div>
  );
}

export function InspectorSwitch({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-3">
      <label htmlFor={id} className="min-w-0 cursor-pointer">
        <span className="block text-foreground text-xs">{label}</span>
        {hint ? (
          <span className="block text-[11px] text-muted-foreground/80 leading-snug">
            {hint}
          </span>
        ) : null}
      </label>
      <Switch id={id} checked={checked} onCheckedChange={onChange} size="sm" />
    </div>
  );
}

export function DraftInput({
  value,
  onCommit,
  placeholder,
  ariaLabel,
}: {
  value: string;
  onCommit: (value: string) => void;
  placeholder?: string;
  ariaLabel: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    if (draft !== value) onCommit(draft);
  };
  return (
    <Input
      value={draft}
      placeholder={placeholder}
      aria-label={ariaLabel}
      className="h-8"
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") commit();
      }}
    />
  );
}

export function DraftTextarea({
  value,
  onCommit,
  ariaLabel,
  mono,
  rows = 6,
  placeholder,
}: {
  value: string;
  onCommit: (value: string) => void;
  ariaLabel: string;
  mono?: boolean;
  rows?: number;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  return (
    <Textarea
      value={draft}
      rows={rows}
      placeholder={placeholder}
      aria-label={ariaLabel}
      className={mono ? "font-mono text-[11.5px] leading-relaxed" : "text-xs"}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        if (draft !== value) onCommit(draft);
      }}
      onKeyDown={(event) => {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          if (draft !== value) onCommit(draft);
        }
      }}
    />
  );
}

export function MathSelect({
  value,
  onChange,
}: {
  value: MathValue;
  onChange: (value: MathValue) => void;
}) {
  return (
    <Select
      value={value}
      onValueChange={(next: MathValue | null) => {
        if (next) onChange(next);
      }}
    >
      <SelectTrigger aria-label="Measure" size="sm" className="w-full">
        <SelectValue>
          {(selected: MathValue) => mathLabel(selected)}
        </SelectValue>
      </SelectTrigger>
      <SelectContent align="start" side="bottom" sideOffset={4}>
        {MATH_OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function OptionSelect({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
  ariaLabel: string;
}) {
  const labelOf = (selected: string) =>
    options.find((option) => option.value === selected)?.label ?? selected;
  return (
    <Select
      value={value}
      onValueChange={(next: string | null) => {
        if (next) onChange(next);
      }}
    >
      <SelectTrigger aria-label={ariaLabel} size="sm" className="w-full">
        <SelectValue>{(selected: string) => labelOf(selected)}</SelectValue>
      </SelectTrigger>
      <SelectContent align="start" side="bottom" sideOffset={4}>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  ariaLabel,
}: {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (value: T) => void;
  ariaLabel: string;
}) {
  return (
    <ToggleGroup
      value={[value]}
      onValueChange={(next: string[]) => {
        const selected = next[0] as T | undefined;
        if (selected && selected !== value) onChange(selected);
      }}
      aria-label={ariaLabel}
    >
      {options.map((option) => (
        <ToggleGroupItem
          key={option.value}
          value={option.value}
          size="sm"
          variant="outline"
          className={settingsToggleItemClassName}
        >
          {option.label}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

export function ControlNote({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md bg-muted/50 px-2.5 py-2 text-[11.5px] text-muted-foreground leading-snug">
      {children}
    </div>
  );
}
