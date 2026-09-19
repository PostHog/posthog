import { CreditCard } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
  MenuLabel,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { Adapter } from "@posthog/shared";
import { SubscriptionBillingItems } from "@posthog/ui/features/sessions/components/SubscriptionBillingItems";
import {
  subscriptionBillingHint,
  subscriptionBillingLabel,
  subscriptionBillingVisible,
} from "@posthog/ui/features/sessions/components/subscriptionBilling";
import { useCloudBillingBlockReason } from "@posthog/ui/features/sessions/components/useCloudBillingBlockReason";
import {
  useAdapterSubscription,
  type WorkspaceModeForAccess,
} from "@posthog/ui/features/settings/adapterSubscription";
import { useState } from "react";

const TOOLTIP_DELAY_MS = 150;

interface BillingChipProps {
  adapter: Adapter;
  /** Workspace mode of the task being composed; cloud disables plan billing. */
  workspaceMode?: WorkspaceModeForAccess;
  disabled?: boolean;
}

/**
 * Who pays for the run, on the composer's toolbar row. The billing pick also
 * lives two levels inside the model menu, where a closed composer never shows
 * it. The stored pick is not always what runs, so the chip reads the resolved
 * access and names a blocked cloud pick as unavailable.
 */
export function BillingChip({
  adapter,
  workspaceMode,
  disabled,
}: BillingChipProps): React.JSX.Element | null {
  const [open, setOpen] = useState(false);
  const subscription = useAdapterSubscription(adapter);
  const blockReason = useCloudBillingBlockReason(
    adapter,
    subscription,
    workspaceMode,
  );
  if (!subscriptionBillingVisible(adapter, subscription, workspaceMode)) {
    return null;
  }
  const label = subscriptionBillingLabel(
    adapter,
    subscription,
    workspaceMode,
    blockReason,
  );

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <TooltipProvider delay={TOOLTIP_DELAY_MS}>
        <Tooltip disableHoverablePopup>
          <TooltipTrigger
            render={
              <DropdownMenuTrigger
                render={
                  <Button
                    type="button"
                    variant="default"
                    size="sm"
                    disabled={disabled}
                    aria-label={`Billing: ${label}`}
                  >
                    <CreditCard size={12} weight="bold" />
                    <span>{label}</span>
                  </Button>
                }
              />
            }
          />
          <TooltipContent side="top" className="max-w-60">
            {subscriptionBillingHint(
              adapter,
              subscription,
              workspaceMode,
              blockReason,
            )}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={6}
        className="min-w-[200px]"
      >
        <MenuLabel>Billing</MenuLabel>
        <SubscriptionBillingItems
          adapter={adapter}
          subscription={subscription}
          workspaceMode={workspaceMode}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
