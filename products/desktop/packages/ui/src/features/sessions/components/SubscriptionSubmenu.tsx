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

export const SUBSCRIPTION_LOGIN_ACTION: Record<Adapter, string> = {
  claude: "claude-login",
  codex: "codex-login",
};

const CLOUD_ONLY_REASON: Record<Adapter, string> = {
  claude:
    "Claude plan billing is unavailable for cloud tasks. Try again later.",
  codex:
    "OpenAI billing only works for local and worktree tasks. Cloud tasks always use PostHog.",
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
  const cloudAvailable = adapter === "claude" && subscription.cloudFlagEnabled;
  if (
    cloudTask
      ? !subscription.flagEnabled &&
        !cloudAvailable &&
        !subscription.cloudSubscriptionOn
      : !subscription.flagEnabled
  ) {
    return null;
  }
  const providerLabel = PROVIDER_LABEL[adapter];
  const value: ModelAccess = cloudTask
    ? subscriptionModelAccess(subscription, "cloud")
    : subscription.subscriptionOn
      ? "own-subscription"
      : "posthog-gateway";
  const valueLabel =
    subscriptionModelAccess(subscription, workspaceMode ?? "local") ===
    "own-subscription"
      ? providerLabel
      : "PostHog";

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
            cloudTask && adapter === "claude"
              ? subscription.setCloudSubscriptionOn?.(
                  next === "own-subscription",
                )
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
        {!cloudTask &&
          subscription.subscriptionOn &&
          !subscription.loggedIn && (
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
