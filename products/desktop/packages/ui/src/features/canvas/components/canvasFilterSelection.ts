import type { ReactNode } from "react";

export interface CanvasFilterOption {
  value: string;
  label: string;
  searchLabel?: string;
  icon?: ReactNode;
}

function selectedOptions(
  options: readonly CanvasFilterOption[],
  values: readonly string[],
): CanvasFilterOption[] {
  const selectedValues = new Set(values);
  return options.filter(
    (option) => option.value !== "" && selectedValues.has(option.value),
  );
}

export function summarizeSpaceSelection(
  options: readonly CanvasFilterOption[],
  values: readonly string[],
): string {
  const selected = selectedOptions(options, values);
  if (selected.length === 0) return "Every space";
  if (selected.length === 1) return selected[0].label;
  return `${selected.length} spaces`;
}

export function summarizeCreatorSelection(
  options: readonly CanvasFilterOption[],
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
