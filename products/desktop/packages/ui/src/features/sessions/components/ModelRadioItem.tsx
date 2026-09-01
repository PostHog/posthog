import { Lock } from "@phosphor-icons/react";
import { DropdownMenuRadioItem } from "@posthog/quill";
import { isRestrictedModel } from "@posthog/ui/features/billing/modelGate";
import { ModelCostChip } from "@posthog/ui/features/sessions/components/ModelCostChip";

/**
 * Model picker entry. Plan-restricted models render dimmed with a lock;
 * picking one is intercepted by the selector's change handler, which opens
 * the upgrade gate instead of selecting. Priced models carry a per-token
 * cost multiplier chip.
 */
export function ModelRadioItem({
  model,
  closeOnClick,
}: {
  model: {
    value: string;
    name: string;
    _meta?: Record<string, unknown> | null;
  };
  closeOnClick?: boolean;
}) {
  const restricted = isRestrictedModel(model);
  return (
    <DropdownMenuRadioItem
      value={model.value}
      closeOnClick={closeOnClick}
      className={restricted ? "opacity-60" : undefined}
    >
      <span className="whitespace-nowrap">{model.name}</span>
      {restricted ? (
        <Lock size={11} className="ml-auto text-muted-foreground" />
      ) : (
        <ModelCostChip modelId={model.value} />
      )}
    </DropdownMenuRadioItem>
  );
}
