import { Lock, Prohibit } from "@phosphor-icons/react";
import {
  DropdownMenuRadioItem,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { isRestrictedModel } from "@posthog/ui/features/billing/modelGate";
import { ModelCostChip } from "@posthog/ui/features/sessions/components/ModelCostChip";

/**
 * Model picker entry. Plan-restricted models render dimmed with a lock;
 * picking one is intercepted by the selector's change handler, which opens
 * the upgrade gate instead of selecting. Priced models carry a per-token
 * cost multiplier chip. A model the current billing source cannot run
 * renders dimmed and names the reason on hover.
 */
export function ModelRadioItem({
  model,
  closeOnClick,
  unavailableReason,
}: {
  model: {
    value: string;
    name: string;
    _meta?: Record<string, unknown> | null;
  };
  closeOnClick?: boolean;
  unavailableReason?: string;
}) {
  const restricted = isRestrictedModel(model);
  const label = <span className="whitespace-nowrap">{model.name}</span>;
  return (
    <DropdownMenuRadioItem
      value={model.value}
      closeOnClick={closeOnClick}
      className={restricted || unavailableReason ? "opacity-60" : undefined}
    >
      {unavailableReason ? (
        <Tooltip disableHoverablePopup>
          <TooltipTrigger render={label} />
          <TooltipContent side="right" className="max-w-56">
            {unavailableReason}
          </TooltipContent>
        </Tooltip>
      ) : (
        label
      )}
      {unavailableReason ? (
        <Prohibit size={11} className="ml-auto text-muted-foreground" />
      ) : restricted ? (
        <Lock size={11} className="ml-auto text-muted-foreground" />
      ) : (
        <ModelCostChip modelId={model.value} />
      )}
    </DropdownMenuRadioItem>
  );
}
