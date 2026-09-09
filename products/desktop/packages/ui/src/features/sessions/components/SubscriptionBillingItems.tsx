import {
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { Adapter, ModelAccess } from "@posthog/shared";
import {
  CLOUD_ONLY_REASON,
  cloudBillingAvailable,
  LOGIN_NOTE,
  PROVIDER_LABEL,
  SUBSCRIPTION_LOGIN_ACTION,
} from "@posthog/ui/features/sessions/components/subscriptionBilling";
import {
  type AdapterSubscription,
  applyModelAccess,
  subscriptionModelAccess,
  type WorkspaceModeForAccess,
} from "@posthog/ui/features/settings/adapterSubscription";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";

const TOOLTIP_DELAY_MS = 150;

interface SubscriptionBillingItemsProps {
  adapter: Adapter;
  subscription: AdapterSubscription;
  closeOnChange?: boolean;
  workspaceMode?: WorkspaceModeForAccess;
}

/**
 * The billing pick itself, shared by the model menu's submenu and the
 * composer's billing chip so both edit through one surface.
 */
export function SubscriptionBillingItems({
  adapter,
  subscription,
  closeOnChange = false,
  workspaceMode,
}: SubscriptionBillingItemsProps): React.JSX.Element {
  const cloudTask = workspaceMode === "cloud";
  const cloudAvailable = cloudBillingAvailable(adapter, subscription);
  const providerLabel = PROVIDER_LABEL[adapter];
  const value: ModelAccess = cloudTask
    ? subscriptionModelAccess(subscription, "cloud")
    : subscription.subscriptionOn
      ? "own-subscription"
      : "posthog-gateway";

  return (
    <>
      <DropdownMenuRadioGroup
        value={value}
        onValueChange={(next) =>
          cloudTask && adapter === "claude"
            ? subscription.setCloudSubscriptionOn?.(next === "own-subscription")
            : applyModelAccess(
                adapter,
                next === "own-subscription"
                  ? "own-subscription"
                  : "posthog-gateway",
                subscription.loggedIn,
              )
        }
      >
        <DropdownMenuRadioItem
          value="posthog-gateway"
          closeOnClick={closeOnChange}
        >
          PostHog
        </DropdownMenuRadioItem>
        {cloudTask && !cloudAvailable ? (
          <TooltipProvider delay={TOOLTIP_DELAY_MS}>
            <Tooltip disableHoverablePopup>
              <TooltipTrigger render={<span className="flex" />}>
                <DropdownMenuRadioItem
                  value="own-subscription"
                  closeOnClick={closeOnChange}
                  disabled
                  className="opacity-60"
                >
                  {providerLabel}
                </DropdownMenuRadioItem>
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-60">
                {CLOUD_ONLY_REASON[adapter]}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : (
          <DropdownMenuRadioItem
            value="own-subscription"
            closeOnClick={closeOnChange}
          >
            {providerLabel}
          </DropdownMenuRadioItem>
        )}
      </DropdownMenuRadioGroup>
      {!cloudTask && subscription.subscriptionOn && !subscription.loggedIn && (
        // A quiet inline note rather than a permanent menu row: it appears
        // only once the provider option is picked without a confirmed
        // login, and sessions keep running on PostHog until the login
        // completes. Unknown status counts as not logged in, so the note
        // stays reachable when the status check cannot run or is pending.
        <div className="px-2 py-1.5 text-muted-foreground text-xs">
          <button
            type="button"
            className="underline underline-offset-2 hover:text-foreground"
            onClick={() =>
              openSettings("harness", SUBSCRIPTION_LOGIN_ACTION[adapter])
            }
          >
            {LOGIN_NOTE[adapter].link}
          </button>
          {LOGIN_NOTE[adapter].rest}
        </div>
      )}
    </>
  );
}
