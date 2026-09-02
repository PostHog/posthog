import { SignIn } from "@phosphor-icons/react";
import {
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@posthog/quill";
import type { Adapter, ModelAccess } from "@posthog/shared";
import {
  applyModelAccess,
  useAdapterSubscription,
} from "@posthog/ui/features/settings/adapterSubscription";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";

const PLAN_LABEL: Record<Adapter, string> = {
  claude: "Your Claude plan",
  codex: "Your ChatGPT plan",
};

const LOGIN_LABEL: Record<Adapter, string> = {
  claude: "Log in to Claude Code",
  codex: "Log in to ChatGPT",
};

export const SUBSCRIPTION_LOGIN_ACTION: Record<Adapter, string> = {
  claude: "claude-login",
  codex: "codex-login",
};

interface SubscriptionSubmenuProps {
  adapter: Adapter;
  closeOnChange?: boolean;
}

export function SubscriptionSubmenu({
  adapter,
  closeOnChange = false,
}: SubscriptionSubmenuProps): React.JSX.Element | null {
  const subscription = useAdapterSubscription(adapter);
  if (!subscription.flagEnabled) {
    return null;
  }

  const planLabel = PLAN_LABEL[adapter];
  const value: ModelAccess = subscription.subscriptionOn
    ? "own-subscription"
    : "posthog-gateway";
  const valueLabel =
    subscription.subscriptionOn && subscription.loggedIn
      ? planLabel
      : "PostHog credits";

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <span>Billing</span>
        <span className="flex-1 text-right text-muted-foreground">
          {valueLabel}
        </span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuRadioGroup
          value={value}
          onValueChange={(next) =>
            applyModelAccess(
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
            PostHog credits
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem
            value="own-subscription"
            closeOnClick={closeOnChange}
            disabled={!subscription.loggedIn}
          >
            {planLabel}
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        {subscription.loggedIn ? null : (
          <DropdownMenuItem
            onClick={() =>
              openSettings("harness", SUBSCRIPTION_LOGIN_ACTION[adapter])
            }
          >
            <SignIn size={12} />
            {LOGIN_LABEL[adapter]}
          </DropdownMenuItem>
        )}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
