import type { ReactNode } from "react";

export interface CanvasFilterOption<Value extends string = string> {
  value: Value;
  label: string;
  searchLabel?: string;
  icon?: ReactNode;
}

export interface CanvasMultiSelectOption
  extends Omit<CanvasFilterOption, "value"> {
  value: string | null;
}

function selectedOptions(
  options: readonly CanvasMultiSelectOption[],
  values: readonly string[],
): CanvasMultiSelectOption[] {
  const selectedValues = new Set(values);
  return options.filter(
    (option) => option.value !== null && selectedValues.has(option.value),
  );
}

export function summarizeSpaceSelection(
  options: readonly CanvasMultiSelectOption[],
  values: readonly string[],
): string {
  const selected = selectedOptions(options, values);
  if (selected.length === 0) return "Every space";
  if (selected.length === 1) return selected[0].label;
  return `${selected.length} spaces`;
}

export function summarizeCreatorSelection(
  options: readonly CanvasMultiSelectOption[],
  values: readonly string[],
): string {
  const selected = selectedOptions(options, values);
  if (selected.length === 0) return "Anyone";
  if (selected.length === 1) return selected[0].label;

  const includesMe = selected.some((option) => option.label === "Me");
  if (!includesMe) return `${selected.length} users`;

  const otherUserCount = selected.length - 1;
  return `Me + ${otherUserCount} ${otherUserCount === 1 ? "user" : "users"}`;
}
