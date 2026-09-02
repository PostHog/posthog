import { ActionSelector } from "@posthog/ui/primitives/ActionSelector";
import { type BasePermissionProps, toSelectorOptions } from "./types";

export function ReadPermission({
  toolCall,
  options,
  onSelect,
  onCancel,
}: BasePermissionProps) {
  return (
    <ActionSelector
      title={toolCall.title ?? "Read file"}
      question="Do you want to allow reading this file?"
      options={toSelectorOptions(options)}
      onSelect={onSelect}
      onCancel={onCancel}
    />
  );
}
