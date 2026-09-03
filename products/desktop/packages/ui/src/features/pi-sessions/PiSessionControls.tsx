import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { CaretDown, Lightning, PiIcon, Stack } from "@phosphor-icons/react";
import type {
  PiModelSelection,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  MenuLabel,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import type { PiModelAccess, PiSubscriptionProvider } from "@posthog/shared";
import {
  type AgentHarness,
  HarnessSubmenu,
} from "@posthog/ui/features/sessions/components/HarnessSubmenu";
import {
  ModelCostChip,
  ModelCostFooter,
} from "@posthog/ui/features/sessions/components/ModelCostChip";
import { ModelSelectList } from "@posthog/ui/features/sessions/components/ModelSelectList";
import type { MessagingMode } from "@posthog/ui/features/sessions/messagingModeStore";
import type { WorkspaceModeForAccess } from "@posthog/ui/features/settings/adapterSubscription";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import {
  applyPiModelAccess,
  type PiSubscription,
  usePiSubscription,
} from "@posthog/ui/features/settings/piSubscription";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useState } from "react";

const TOOLTIP_DELAY_MS = 150;

const PI_BILLING_LABEL: Record<PiSubscriptionProvider, string> = {
  anthropic: "Claude",
  "openai-codex": "ChatGPT",
};

const PI_BILLING_LOGIN_NOTE: Record<
  PiSubscriptionProvider,
  { link: string; rest: string }
> = {
  anthropic: { link: "Log in to Claude", rest: " to use Claude billing." },
  "openai-codex": {
    link: "Connect ChatGPT",
    rest: " to use ChatGPT billing.",
  },
};

const PI_BILLING_CLOUD_ONLY_REASON: Record<PiSubscriptionProvider, string> = {
  anthropic:
    "Claude billing only works for local and worktree tasks. Cloud tasks always use PostHog.",
  "openai-codex":
    "ChatGPT billing only works for local and worktree tasks. Cloud tasks always use PostHog.",
};

interface PiBillingSubmenuProps {
  /** Workspace mode of the task being composed; cloud forces PostHog credits. */
  workspaceMode?: WorkspaceModeForAccess;
  closeOnChange?: boolean;
}

/**
 * Pi's equivalent of `SubscriptionSubmenu` (used by Claude/Codex): lets the
 * user pick PostHog credits or one of their connected Pi subscriptions for
 * this session, independent of just being logged in. Self-contained like
 * `SubscriptionSubmenu`, so any composer can opt in by rendering it — see
 * `showBillingMenu` on `PiModelSelector` below. Only lists a provider once
 * its rollout flag is on — hidden entirely if neither is.
 */
function PiBillingSubmenu({
  workspaceMode,
  closeOnChange = false,
}: PiBillingSubmenuProps): React.JSX.Element | null {
  const modelAccess = useSettingsStore((state) => state.piModelAccess);
  const anthropicSubscription = usePiSubscription("anthropic");
  const codexSubscription = usePiSubscription("openai-codex");
  const providers: {
    provider: PiSubscriptionProvider;
    subscription: PiSubscription;
  }[] = [
    ...(anthropicSubscription.flagEnabled
      ? [
          {
            provider: "anthropic" as const,
            subscription: anthropicSubscription,
          },
        ]
      : []),
    ...(codexSubscription.flagEnabled
      ? [
          {
            provider: "openai-codex" as const,
            subscription: codexSubscription,
          },
        ]
      : []),
  ];
  if (providers.length === 0) {
    return null;
  }

  // Cloud tasks always bill PostHog credits (see effectivePiSubscriptionProvider),
  // so the provider options are disabled there instead of silently overriding the pick.
  const cloudTask = workspaceMode === "cloud";
  const activeProvider = providers.find((p) => p.provider === modelAccess);
  const valueLabel =
    activeProvider && !cloudTask
      ? PI_BILLING_LABEL[activeProvider.provider]
      : "PostHog";
  const pendingLoginNote = providers.find(
    (p) => p.provider === modelAccess && !p.subscription.loggedIn,
  );

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
          value={cloudTask ? "posthog-gateway" : modelAccess}
          onValueChange={(next) => applyPiModelAccess(next as PiModelAccess)}
        >
          <DropdownMenuRadioItem
            value="posthog-gateway"
            closeOnClick={closeOnChange}
          >
            PostHog
          </DropdownMenuRadioItem>
          {providers.map(({ provider }) =>
            cloudTask ? (
              <TooltipProvider delay={TOOLTIP_DELAY_MS} key={provider}>
                <Tooltip disableHoverablePopup>
                  <TooltipTrigger render={<span className="flex" />}>
                    <DropdownMenuRadioItem
                      value={provider}
                      closeOnClick={closeOnChange}
                      disabled
                      className="opacity-60"
                    >
                      {PI_BILLING_LABEL[provider]}
                    </DropdownMenuRadioItem>
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-60">
                    {PI_BILLING_CLOUD_ONLY_REASON[provider]}
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ) : (
              <DropdownMenuRadioItem
                key={provider}
                value={provider}
                closeOnClick={closeOnChange}
              >
                {PI_BILLING_LABEL[provider]}
              </DropdownMenuRadioItem>
            ),
          )}
        </DropdownMenuRadioGroup>
        {!cloudTask && pendingLoginNote && (
          // A quiet inline note rather than a permanent menu row: it appears
          // only once the provider is picked without a confirmed login, and
          // sessions keep running on PostHog until the login completes.
          <div className="px-2 py-1.5 text-muted-foreground text-xs">
            <button
              type="button"
              className="underline underline-offset-2 hover:text-foreground"
              onClick={() => openSettings("harness")}
            >
              {PI_BILLING_LOGIN_NOTE[pendingLoginNote.provider].link}
            </button>
            {PI_BILLING_LOGIN_NOTE[pendingLoginNote.provider].rest}
          </div>
        )}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

type PiModelOption = PiModelSelection & { name?: string };

interface PiModelSelectorProps {
  models: PiModelOption[];
  currentModel?: PiModelOption;
  thinkingLevel?: PiThinkingLevel;
  thinkingLevels?: PiThinkingLevel[];
  disabled?: boolean;
  isLoading?: boolean;
  onChange: (model: PiModelSelection) => void;
  onThinkingLevelChange?: (level: PiThinkingLevel) => void;
  onHarnessChange?: (harness: AgentHarness) => void;
  /**
   * The full provider-grouped catalog, so the Pi menu offers the same model
   * list as the other harnesses. Picks report the gateway model id and the
   * caller decides whether the pick stays on Pi.
   */
  modelOption?: SessionConfigOption;
  onGatewayModelSelect?: (modelId: string) => void;
  menuOpen?: boolean;
  onMenuOpenChange?: (open: boolean) => void;
  /** Composers opt in; mid-session controls (no restart) leave this off. */
  showBillingMenu?: boolean;
  /** Workspace mode of the task being composed; cloud forces PostHog credits. */
  workspaceMode?: WorkspaceModeForAccess;
}

function modelKey(model: PiModelSelection): string {
  return JSON.stringify([model.provider, model.id]);
}

function modelLabel(model?: PiModelOption): string {
  return model?.name ?? model?.id ?? "Model";
}

const thinkingLevelLabels: Record<PiThinkingLevel, string> = {
  off: "Off",
  minimal: "Minimal",
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra High",
  max: "Max",
};

export function PiModelSelector({
  models,
  currentModel,
  thinkingLevel,
  thinkingLevels = [],
  disabled,
  isLoading,
  onChange,
  onThinkingLevelChange,
  onHarnessChange,
  modelOption,
  onGatewayModelSelect,
  menuOpen,
  onMenuOpenChange,
  showBillingMenu,
  workspaceMode,
}: PiModelSelectorProps) {
  const [internalMenuOpen, setInternalMenuOpen] = useState(false);
  const open = menuOpen ?? internalMenuOpen;
  const setOpen = onMenuOpenChange ?? setInternalMenuOpen;
  const gatewayModelSelect =
    modelOption?.type === "select" && onGatewayModelSelect
      ? modelOption
      : undefined;

  if (models.length === 0) {
    if (isLoading) {
      // Keep the dropdown mounted while the Pi catalog first loads (a
      // harness switch to Pi): unmounting it closes a menu the user is
      // mid-interaction with.
      return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
          <DropdownMenuTrigger
            render={
              <Button type="button" variant="default" size="sm">
                <span className="text-muted-foreground">
                  <PiIcon size={14} weight="bold" className="translate-y-px" />
                </span>
                <Spinner size={12} />
                Loading...
              </Button>
            }
          />
          <DropdownMenuContent
            align="start"
            side="top"
            sideOffset={6}
            className="min-w-[230px]"
          >
            <DropdownMenuItem disabled>
              <Spinner size={12} />
              Loading models...
            </DropdownMenuItem>
            {onHarnessChange && (
              <HarnessSubmenu
                value="pi"
                includePi
                closeOnChange={false}
                onChange={(harness) => {
                  if (harness !== "pi") {
                    onHarnessChange(harness);
                  }
                }}
              />
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      );
    }
    return null;
  }

  const currentValue = currentModel ? modelKey(currentModel) : "";
  const selectedModel =
    models.find((model) => modelKey(model) === currentValue) ?? currentModel;
  const currentLabel = modelLabel(selectedModel);
  const thinkingLabel = thinkingLevel
    ? (thinkingLevelLabels[thinkingLevel] ?? thinkingLevel)
    : undefined;

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={disabled}
            aria-label={
              thinkingLabel
                ? `Model and reasoning: ${currentLabel} ${thinkingLabel}`
                : `Model: ${currentLabel}`
            }
          >
            <span className="text-muted-foreground">
              <PiIcon size={14} weight="bold" className="translate-y-px" />
            </span>
            <span className="font-medium text-foreground">{currentLabel}</span>
            {thinkingLabel && (
              <span className="font-normal text-muted-foreground/80">
                {thinkingLabel}
              </span>
            )}
            <CaretDown
              size={10}
              weight="bold"
              className="text-muted-foreground"
            />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={6}
        className="min-w-[230px]"
      >
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <span>Model</span>
            <span className="flex-1 text-right text-muted-foreground">
              {currentLabel}
            </span>
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="min-w-[220px]">
            {gatewayModelSelect ? (
              <ModelSelectList
                options={gatewayModelSelect.options}
                currentValue={selectedModel?.id}
                onGated={() => setOpen(false)}
                onSelect={(value) => onGatewayModelSelect?.(value)}
              />
            ) : (
              <>
                <DropdownMenuRadioGroup
                  value={currentValue}
                  onValueChange={(value) => {
                    const model = models.find(
                      (candidate) => modelKey(candidate) === value,
                    );
                    if (model) {
                      onChange(model);
                    }
                  }}
                >
                  {models.map((model) => (
                    <DropdownMenuRadioItem
                      key={modelKey(model)}
                      value={modelKey(model)}
                      closeOnClick={false}
                    >
                      <span className="whitespace-nowrap">
                        {modelLabel(model)}
                      </span>
                      <ModelCostChip modelId={model.id} />
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
                <ModelCostFooter />
              </>
            )}
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        {onHarnessChange && (
          <HarnessSubmenu
            value="pi"
            includePi
            closeOnChange={false}
            onChange={(harness) => {
              if (harness !== "pi") {
                onHarnessChange(harness);
              }
            }}
          />
        )}
        {showBillingMenu && <PiBillingSubmenu workspaceMode={workspaceMode} />}
        {thinkingLevel &&
          onThinkingLevelChange &&
          thinkingLevels.length > 0 && (
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>
                <span>Reasoning</span>
                <span className="flex-1 text-right text-muted-foreground">
                  {thinkingLabel}
                </span>
              </DropdownMenuSubTrigger>
              <DropdownMenuSubContent>
                <DropdownMenuRadioGroup
                  value={thinkingLevel}
                  onValueChange={(value) =>
                    onThinkingLevelChange(value as PiThinkingLevel)
                  }
                >
                  {thinkingLevels.map((level) => (
                    <DropdownMenuRadioItem
                      key={level}
                      value={level}
                      closeOnClick={false}
                    >
                      {thinkingLevelLabels[level] ?? level}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

interface PiMessagingModeSelectorProps {
  mode: MessagingMode;
  queuedCount: number;
  disabled?: boolean;
  onModeChange: (mode: MessagingMode) => void;
}

export function PiMessagingModeSelector({
  mode,
  queuedCount,
  disabled,
  onModeChange,
}: PiMessagingModeSelectorProps) {
  let label = "Queue";
  if (mode === "steer") {
    label = "Steer";
  } else if (queuedCount > 0) {
    label = `Queue (${queuedCount})`;
  }

  const colorClass = mode === "steer" ? "text-purple-11" : "text-gray-11";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={disabled}
            aria-label={`Messaging mode: ${label}`}
          >
            <span className={colorClass}>
              {mode === "steer" ? (
                <Lightning size={12} weight="fill" />
              ) : (
                <Stack size={12} />
              )}
            </span>
            <span className={colorClass}>{label}</span>
            <CaretDown size={10} weight="bold" className={colorClass} />
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={6}
        className="min-w-[240px]"
      >
        <MenuLabel>While Pi is generating</MenuLabel>
        <DropdownMenuRadioGroup
          value={mode}
          onValueChange={(value) => onModeChange(value as MessagingMode)}
        >
          <DropdownMenuRadioItem value="steer">
            Steer after the current tool finishes
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="queue">
            Queue for the next turn
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
