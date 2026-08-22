import { Lock } from "@phosphor-icons/react";
import {
  modelPriceTier,
  modelPriceTierLabel,
  modelPriceTierMarker,
} from "@posthog/core/billing/modelPriceTiers";
import { DropdownMenuRadioItem } from "@posthog/quill";
import { isRestrictedModel } from "@posthog/ui/features/billing/modelGate";

/**
 * Model picker entry. Plan-restricted models render dimmed with a lock;
 * picking one is intercepted by the selector's change handler, which opens
 * the upgrade gate instead of selecting. Known model families carry a
 * relative cost marker ($ to $$$); unknown ones show none.
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
  const tier = restricted ? null : modelPriceTier(model.value);
  return (
    <DropdownMenuRadioItem
      value={model.value}
      closeOnClick={closeOnClick}
      className={restricted ? "opacity-60" : undefined}
    >
      <span className="whitespace-nowrap">{model.name}</span>
      {restricted && (
        <Lock size={11} className="ml-auto text-muted-foreground" />
      )}
      {tier !== null && (
        // Presentational so the item's accessible name stays the model name;
        // the title carries the meaning for pointer users.
        <span
          className="ml-auto pl-3 text-[10px] text-muted-foreground tracking-tight"
          title={modelPriceTierLabel(tier)}
          aria-hidden="true"
        >
          {modelPriceTierMarker(tier)}
        </span>
      )}
    </DropdownMenuRadioItem>
  );
}
