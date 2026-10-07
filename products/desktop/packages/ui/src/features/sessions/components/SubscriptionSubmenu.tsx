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
  modelAccess?: ModelAccess;
  onModelAccessChange?: (access: ModelAccess) => void;
}

export function SubscriptionSubmenu({
  adapter,
  closeOnChange = false,
  workspaceMode,
  modelAccess,
  onModelAccessChange,
}: SubscriptionSubmenuProps): React.JSX.Element | null {
  const subscription = useAdapterSubscription(adapter);
  const cloudTask = workspaceMode === "cloud";
  const cloudAvailable = cloudTask && subscription.cloudFlagEnabled;
  const available = subscription.flagEnabled || cloudAvailable;
  if (!available || !onModelAccessChange) {
    return null;
  }

  const providerLabel = PROVIDER_LABEL[adapter];
  const selected =
    modelAccess ??
    subscriptionModelAccess(subscription, workspaceMode ?? "local");
  const valueLabel =
    selected === "own-subscription" ? providerLabel : "PostHog";
  const providerLocked = cloudTask && !cloudAvailable;
  const showLoginNote =
    !cloudTask && selected === "own-subscription" && !subscription.loggedIn;

  const selectAccess = (next: string): void => {
    onModelAccessChange(
      next === "own-subscription" ? "own-subscription" : "posthog-gateway",
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
        <div className="max-w-64 px-2 py-1.5 text-muted-foreground text-xs">
          For this task only. Your default stays the same.
        </div>
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
