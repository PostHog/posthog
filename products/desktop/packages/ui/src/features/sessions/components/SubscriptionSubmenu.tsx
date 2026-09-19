import {
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@posthog/quill";
import type { Adapter } from "@posthog/shared";
import { SubscriptionBillingItems } from "@posthog/ui/features/sessions/components/SubscriptionBillingItems";
import {
  subscriptionBillingLabel,
  subscriptionBillingVisible,
} from "@posthog/ui/features/sessions/components/subscriptionBilling";
import {
  useAdapterSubscription,
  type WorkspaceModeForAccess,
} from "@posthog/ui/features/settings/adapterSubscription";

interface SubscriptionSubmenuProps {
  adapter: Adapter;
  closeOnChange?: boolean;
  workspaceMode?: WorkspaceModeForAccess;
}

export function SubscriptionSubmenu({
  adapter,
  closeOnChange = false,
  workspaceMode,
}: SubscriptionSubmenuProps): React.JSX.Element | null {
  const subscription = useAdapterSubscription(adapter);
  if (!subscriptionBillingVisible(adapter, subscription, workspaceMode)) {
    return null;
  }

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <span>Billing</span>
        <span className="flex-1 text-right text-muted-foreground">
          {subscriptionBillingLabel(adapter, subscription, workspaceMode)}
        </span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <SubscriptionBillingItems
          adapter={adapter}
          subscription={subscription}
          closeOnChange={closeOnChange}
          workspaceMode={workspaceMode}
        />
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
