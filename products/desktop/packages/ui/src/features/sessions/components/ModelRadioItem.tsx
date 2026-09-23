import { Lock, Prohibit } from "@phosphor-icons/react";
import type { ModelPickerOption } from "@posthog/core/billing/modelPricing";
import {
  DropdownMenuRadioItem,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { isRestrictedModel } from "@posthog/ui/features/billing/modelGate";
import { ModelCostChip } from "@posthog/ui/features/sessions/components/ModelCostChip";

const TOOLTIP_DELAY_MS = 150;

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
  model: ModelPickerOption;
  closeOnClick?: boolean;
  unavailableReason?: string;
}) {
  const restricted = isRestrictedModel(model);
  const item = (
    <DropdownMenuRadioItem
      value={model.value}
      closeOnClick={closeOnClick}
      className={restricted || unavailableReason ? "opacity-60" : undefined}
    >
      <span className="whitespace-nowrap">{model.name}</span>
      <span className="ml-auto flex items-center">
        {model.kind === "priced" ? <ModelCostChip cost={model.cost} /> : null}
        {unavailableReason ? (
          <Prohibit size={11} className="ml-1 text-muted-foreground" />
        ) : restricted ? (
          <Lock size={11} className="ml-1 text-muted-foreground" />
        ) : null}
      </span>
    </DropdownMenuRadioItem>
  );

  if (!unavailableReason) {
    return item;
  }

  return (
    <TooltipProvider delay={TOOLTIP_DELAY_MS}>
      <Tooltip disableHoverablePopup>
        <TooltipTrigger render={item} />
        <TooltipContent side="right" className="max-w-60">
          {unavailableReason}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
