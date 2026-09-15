import type { Icon } from "@phosphor-icons/react";

export function AutoresearchPromptRequirement({
  icon: RequirementIcon,
  label,
}: {
  icon: Icon;
  label: string;
}) {
  return (
    <li className="flex items-center gap-1.5 text-muted-foreground text-xs">
      <RequirementIcon size={13} className="shrink-0" />
      <span>{label}</span>
    </li>
  );
}
