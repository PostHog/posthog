import { ActionSelector } from "@posthog/ui/primitives/ActionSelector";
import { type BasePermissionProps, toSelectorOptions } from "./types";

export function MovePermission({
  toolCall,
  options,
  onSelect,
  onCancel,
}: BasePermissionProps) {
  return (
    <ActionSelector
      title={toolCall.title ?? "Move file"}
      question="Allow this file move?"
      options={toSelectorOptions(options)}
      onSelect={onSelect}
      onCancel={onCancel}
    />
  );
}
