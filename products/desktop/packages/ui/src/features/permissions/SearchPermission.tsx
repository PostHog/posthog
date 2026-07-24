import { ActionSelector } from "@posthog/ui/primitives/ActionSelector";
import { type BasePermissionProps, toSelectorOptions } from "./types";

export function SearchPermission({
  toolCall,
  options,
  onSelect,
  onCancel,
}: BasePermissionProps) {
  return (
    <ActionSelector
      title={toolCall.title ?? "Search"}
      question="Allow this search?"
      options={toSelectorOptions(options)}
      onSelect={onSelect}
      onCancel={onCancel}
    />
  );
}
