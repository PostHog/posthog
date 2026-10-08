import {
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { Adapter, ModelAccess } from "@posthog/shared";
import {
  applyModelAccess,
  subscriptionModelAccess,
  useAdapterSubscription,
  type WorkspaceModeForAccess,
} from "@posthog/ui/features/settings/adapterSubscription";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { SUBSCRIPTION_LOGIN_ACTION } from "@posthog/ui/features/settings/subscriptionActions";

const PROVIDER_LABEL: Record<Adapter, string> = {
  claude: "Anthropic",
  codex: "OpenAI",
};

const LOGIN_NOTE: Record<Adapter, { link: string; rest: string }> = {
  claude: {
    link: "Log in to Claude Code",
    rest: " to use Anthropic billing.",
  },
  codex: {
    link: "Connect ChatGPT",
    rest: " to use OpenAI billing.",
  },
};

const CLOUD_ONLY_REASON: Record<Adapter, string> = {
  claude:
    "Claude plan billing is unavailable for cloud tasks. Try again later.",
  codex:
    "ChatGPT plan billing is unavailable for cloud tasks. Try again later.",
};

const TOOLTIP_DELAY_MS = 150;

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
  const cloudTask = workspaceMode === "cloud";
  const cloudAvailable = cloudTask && subscription.cloudFlagEnabled;
  const available = subscription.flagEnabled || cloudAvailable;
  if (!available) {
    return null;
  }

  const providerLabel = PROVIDER_LABEL[adapter];
  const selected: ModelAccess = cloudTask
    ? subscriptionModelAccess(subscription, "cloud")
    : subscription.subscriptionOn
      ? "own-subscription"
      : "posthog-gateway";
  const effective = subscriptionModelAccess(
    subscription,
    workspaceMode ?? "local",
  );
  const valueLabel =
    effective === "own-subscription" ? providerLabel : "PostHog";
  const providerLocked = cloudTask && !cloudAvailable;
  const showLoginNote =
    !cloudTask && subscription.subscriptionOn && !subscription.loggedIn;

  const selectAccess = (next: string): void => {
    const ownSubscription = next === "own-subscription";
    if (cloudTask) {
      subscription.setCloudSubscriptionOn(ownSubscription);
      return;
    }
    applyModelAccess(
      adapter,
      ownSubscription ? "own-subscription" : "posthog-gateway",
      subscription.loggedIn,
    );
  };

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <span>Billing</span>
        <span className="flex-1 text-right text-muted-foreground">
          {valueLabel}
        </span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent>
        <DropdownMenuRadioGroup value={selected} onValueChange={selectAccess}>
          <DropdownMenuRadioItem
            value="posthog-gateway"
            closeOnClick={closeOnChange}
          >
            PostHog
          </DropdownMenuRadioItem>
          {providerLocked ? (
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
        {showLoginNote && (
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
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
