import { SignIn } from "@phosphor-icons/react";
import {
  DropdownMenuItem,
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
  useAdapterSubscription,
  type WorkspaceModeForAccess,
} from "@posthog/ui/features/settings/adapterSubscription";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";

const PROVIDER_LABEL: Record<Adapter, string> = {
  claude: "Anthropic",
  codex: "OpenAI",
};

const LOGIN_LABEL: Record<Adapter, string> = {
  claude: "Log in to Claude Code",
  codex: "Log in to ChatGPT",
};

export const SUBSCRIPTION_LOGIN_ACTION: Record<Adapter, string> = {
  claude: "claude-login",
  codex: "codex-login",
};

const CLOUD_ONLY_REASON: Record<Adapter, string> = {
  claude:
    "Anthropic billing only works for local and worktree tasks. Cloud tasks always use PostHog.",
  codex:
    "OpenAI billing only works for local and worktree tasks. Cloud tasks always use PostHog.",
};

const TOOLTIP_DELAY_MS = 150;

interface SubscriptionSubmenuProps {
  adapter: Adapter;
  closeOnChange?: boolean;
  /** Workspace mode of the task being composed; cloud forces PostHog credits. */
  workspaceMode?: WorkspaceModeForAccess;
}

export function SubscriptionSubmenu({
  adapter,
  closeOnChange = false,
  workspaceMode,
}: SubscriptionSubmenuProps): React.JSX.Element | null {
  const subscription = useAdapterSubscription(adapter);
  if (!subscription.flagEnabled) {
    return null;
  }

  // Cloud tasks always bill PostHog credits (see effectiveModelAccess), so the
  // provider option is disabled there instead of silently overriding the pick.
  const cloudTask = workspaceMode === "cloud";
  const providerLabel = PROVIDER_LABEL[adapter];
  const value: ModelAccess =
    cloudTask || !subscription.subscriptionOn
      ? "posthog-gateway"
      : "own-subscription";
  const valueLabel =
    subscription.subscriptionOn && subscription.loggedIn && !cloudTask
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
            PostHog
          </DropdownMenuRadioItem>
          {cloudTask ? (
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
              disabled={!subscription.loggedIn}
            >
              {providerLabel}
            </DropdownMenuRadioItem>
          )}
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
