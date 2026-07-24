import { Lock } from "@phosphor-icons/react";
import { DropdownMenuRadioItem } from "@posthog/quill";
import { isRestrictedModel } from "@posthog/ui/features/billing/modelGate";

/**
 * Model picker entry. Plan-restricted models render dimmed with a lock;
 * picking one is intercepted by the selector's change handler, which opens
 * the upgrade gate instead of selecting.
 */
export function ModelRadioItem({
  model,
}: {
  model: {
    value: string;
    name: string;
    _meta?: Record<string, unknown> | null;
  };
}) {
  const restricted = isRestrictedModel(model);
  return (
    <DropdownMenuRadioItem
      value={model.value}
      className={restricted ? "opacity-60" : undefined}
    >
      <span className="whitespace-nowrap">{model.name}</span>
      {restricted && (
        <Lock size={11} className="ml-auto text-muted-foreground" />
      )}
    </DropdownMenuRadioItem>
  );
}
