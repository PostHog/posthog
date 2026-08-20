import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { ArrowCounterClockwise, Lightning } from "@phosphor-icons/react";
import {
  getCapabilityLadder,
  getReasoningEffortOptions,
} from "@posthog/agent/adapters/reasoning-effort";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@posthog/quill";
import {
  adapterForModelId,
  FAST_MODE_FLAG,
  isAnthropicModelId,
  isDefaultSelectOption,
  isRestrictedModelOption,
  type ModelAccess,
  selectOptionDocsUrl,
  selectOptionHarness,
} from "@posthog/shared";
import {
  EFFORT_LEVEL_LABELS,
  FAST_MODE_DOCS_URLS,
} from "@posthog/shared/domain-types";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  type AgentHarness,
  HarnessSubmenu,
} from "@posthog/ui/features/sessions/components/HarnessSubmenu";
import { ModelSelectList } from "@posthog/ui/features/sessions/components/ModelSelectList";
import { SubscriptionSubmenu } from "@posthog/ui/features/sessions/components/SubscriptionSubmenu";
import type { WorkspaceModeForAccess } from "@posthog/ui/features/settings/adapterSubscription";
import type { AgentAdapter } from "@posthog/ui/features/settings/settingsStore";
import { AnimatedHeight } from "@posthog/ui/primitives/AnimatedHeight";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { AnimatePresence, motion } from "framer-motion";
import { useRef, useState } from "react";
import { flattenSelectOptions } from "../sessionStore";
import { useRetainedConfigOption } from "../useRetainedConfigOption";
import {
  BackRow,
  LevelItem,
  type ReasoningLevelOption,
  ReasoningSliderFace,
} from "./ReasoningLevelDropdown";

// Separates model and effort in a slider stop key; never appears in ids.
const STOP_SEPARATOR = "|";

interface ReasoningLevelSelectorProps {
  thoughtOption?: SessionConfigOption;
  modelOption?: SessionConfigOption;
  adapter?: AgentAdapter;
  contextWindowOption?: SessionConfigOption;
  fastModeOption?: SessionConfigOption;
  onChange?: (value: string) => void;
  onModelChange?: (value: string) => void;
  /**
   * A ladder notch carries a model and an effort together. When one drag moves
   * both, the split onModelChange/onChange callbacks fire back to back with no
   * render between them, so a caller that reads the model from render props in
   * its effort handler sees the old value. Callers that persist the pair as a
   * single value pass this to receive the notch atomically instead.
   */
  onNotchSelect?: (selection: { model: string; effort: string }) => void;
  onAdapterChange?: (adapter: AgentAdapter) => void;
  onHarnessChange?: (harness: AgentHarness) => void;
  /**
   * Called instead of onModelChange when the picked model runs on a
   * different harness, so the caller can switch harness and keep the pick.
   */
  onHarnessModelChange?: (harness: AgentAdapter, model: string) => void;
  includePiHarness?: boolean;
  onConfigOptionChange?: (configId: string, value: string) => void;
  menuOpen?: boolean;
  onMenuOpenChange?: (open: boolean) => void;
  disabled?: boolean;
  isLoading?: boolean;
  modelAccess?: ModelAccess;
  showBillingMenu?: boolean;
  /** Workspace mode of the task being composed; cloud disables plan billing. */
  workspaceMode?: WorkspaceModeForAccess;
  /**
   * The selection shown is inherited rather than picked here — the trigger prefixes it
   * with "Default ·" so an inherited value can't be mistaken for one you chose. Matches
   * the web composer's marker.
   */
  isDefaultSelection?: boolean;
  /**
   * Clears the explicit pick so the configured project/user default applies again.
   * When provided, the "Reset to default" row calls this instead of the built-in
   * reset to the ladder's balanced notch. Matches the web composer's single
   * reset row.
   */
  onResetToDefault?: () => void;
  /**
   * Resetting via onResetToDefault would change nothing, so the row reads
   * disabled. Kept separate from isDefaultSelection, which only drives the
   * trigger's "Default ·" marker — the two diverge when no default applies.
   */
  resetToDefaultDisabled?: boolean;
  /**
   * Position and size the popup against this element instead of the trigger.
   *
   * The popup takes both its placement and its width from its anchor, and the trigger
   * resizes as the label under the cursor changes — so dragging the slider walks the
   * popup around. Callers whose layout lets the trigger move (a right-aligned settings
   * row, say) pass a fixed-size element to hold it still. Composers, where the trigger
   * is left-anchored, need nothing.
   */
  anchor?: React.RefObject<HTMLElement | null>;
}

function toDropdownOptions(
  option: SessionConfigOption,
): ReasoningLevelOption[] {
  if (option.type !== "select") return [];
  return flattenSelectOptions(option.options).map((entry) => ({
    value: entry.value,
    label: entry.name,
    isDefault: isDefaultSelectOption(entry._meta),
    docsUrl: selectOptionDocsUrl(entry._meta),
  }));
}

/**
 * The merged model + reasoning control: one pill ("Model Effort") opening the
 * Faster/Smarter capability slider, with an Advanced view of per-setting
 * submenus (Model, Reasoning, Context Window, Fast Mode) and a reset row.
 */
export function ReasoningLevelSelector({
  thoughtOption,
  modelOption,
  adapter,
  contextWindowOption,
  fastModeOption,
  onChange,
  onModelChange,
  onNotchSelect,
  onAdapterChange,
  onHarnessChange,
  onHarnessModelChange,
  includePiHarness,
  onConfigOptionChange,
  menuOpen,
  onMenuOpenChange,
  disabled,
  isLoading,
  modelAccess,
  showBillingMenu,
  workspaceMode,
  isDefaultSelection,
  onResetToDefault,
  resetToDefaultDisabled,
  anchor,
}: ReasoningLevelSelectorProps) {
  const [internalMenuOpen, setInternalMenuOpen] = useState(false);
  const open = menuOpen ?? internalMenuOpen;
  const setOpen = onMenuOpenChange ?? setInternalMenuOpen;
  const [advanced, setAdvanced] = useState(false);
  // Frozen when the Advanced view is entered: deriving it live from the
  // ladder makes the Back row flash in and out as model picks move on and
  // off a notch while the menu is open.
  const [showBack, setShowBack] = useState(false);
  const pendingChangeRef = useRef<(() => void) | null>(null);
  const displayThought = useRetainedConfigOption(thoughtOption);
  const displayModel = useRetainedConfigOption(modelOption);
  const fastModeFlagEnabled = useFeatureFlag(FAST_MODE_FLAG);

  // An effort-less model has no thought option once the config settles; the
  // pill is the only model picker, so it must stay rendered to switch away.
  const effortless = !thoughtOption && !isLoading;
  const thoughtSelect =
    !effortless && displayThought?.type === "select"
      ? displayThought
      : undefined;
  const effortOptions = thoughtSelect ? toDropdownOptions(thoughtSelect) : [];
  const hasEffort = effortOptions.length > 0;

  const modelSelect =
    displayModel?.type === "select" ? displayModel : undefined;

  const onOwnSubscription =
    adapter === "claude" && modelAccess === "own-subscription";
  const unavailableReason = (modelId: string): string | undefined =>
    onOwnSubscription && !isAnthropicModelId(modelId)
      ? "Anthropic billing cannot run this model. Change billing to PostHog to use it."
      : undefined;

  const handleHarnessSelect = (harness: AgentHarness) => {
    if (harness === adapter) {
      return;
    }

    if (harness === "pi") {
      onHarnessChange?.(harness);
      return;
    }

    if (onHarnessChange) {
      onHarnessChange(harness);
      return;
    }

    onAdapterChange?.(harness);
  };

  // The row stays visible even with model-first wiring: a model pick
  // auto-selects its harness, and the row shows the result and allows a
  // manual override (Pi can run models from both groups).
  const showHarnessSubmenu =
    !!adapter && !!(onAdapterChange || onHarnessChange);

  if (!hasEffort && !modelSelect) {
    if (isLoading) {
      // Keep the dropdown mounted while a harness switch reloads the config:
      // unmounting it here closes a menu the user is mid-interaction with.
      return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
          <DropdownMenuTrigger
            render={
              <Button type="button" variant="default" size="sm">
                <Spinner size={12} />
                Loading...
              </Button>
            }
          />
          <DropdownMenuContent
            align="start"
            side="top"
            sideOffset={6}
            anchor={anchor}
            className="min-w-[230px]"
          >
            <DropdownMenuItem disabled>
              <Spinner size={12} />
              Loading models...
            </DropdownMenuItem>
            {showHarnessSubmenu && adapter && (
              <HarnessSubmenu
                value={adapter}
                includePi={includePiHarness && !!onHarnessChange}
                closeOnChange={false}
                onChange={handleHarnessSelect}
              />
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      );
    }
    return null;
  }

  const isReloading = !effortless && !thoughtOption;
  const isDisabled = disabled || isReloading;

  const currentEffort = thoughtSelect?.currentValue;
  const effortLabel = currentEffort
    ? (effortOptions.find((option) => option.value === currentEffort)?.label ??
      currentEffort)
    : undefined;
  const modelEntries = modelSelect
    ? flattenSelectOptions(modelSelect.options)
    : [];
  const currentModel =
    typeof modelSelect?.currentValue === "string"
      ? modelSelect.currentValue
      : undefined;
  const modelLabel = currentModel
    ? (modelEntries.find((entry) => entry.value === currentModel)?.name ??
      currentModel)
    : undefined;

  const changeModel = (value: string) => {
    if (onModelChange) {
      onModelChange(value);
    } else if (modelSelect) {
      onConfigOptionChange?.(modelSelect.id, value);
    }
  };

  const ladderStops =
    adapter && modelSelect
      ? getCapabilityLadder(adapter).flatMap((notch) => {
          const entry = modelEntries.find(
            (candidate) => candidate.value === notch.model,
          );
          if (!entry || isRestrictedModelOption(entry._meta)) return [];
          if (unavailableReason(notch.model)) return [];
          const efforts = getReasoningEffortOptions(adapter, notch.model) ?? [];
          if (!efforts.some((option) => option.value === notch.effort)) {
            return [];
          }
          return [
            {
              key: `${notch.model}${STOP_SEPARATOR}${notch.effort}`,
              label: `${entry.name ?? notch.model} · ${EFFORT_LEVEL_LABELS[notch.effort]}`,
            },
          ];
        })
      : [];
  const useLadder = ladderStops.length >= 2;
  const stops = useLadder
    ? ladderStops
    : effortOptions.map((option) => ({
        key: option.value,
        label: option.label,
      }));
  const currentStopKey = useLadder
    ? `${currentModel}${STOP_SEPARATOR}${currentEffort}`
    : (currentEffort ?? "");

  // A custom Advanced combination (off the preset ladder) hides the slider:
  // the menu opens straight on the Advanced view until Reset to default puts
  // the session back on a notch.
  const onNotch = useLadder
    ? ladderStops.some((stop) => stop.key === currentStopKey)
    : hasEffort;

  const handleStopSelect = (key: string) => {
    if (key.includes(STOP_SEPARATOR)) {
      const [model, effort] = key.split(STOP_SEPARATOR);
      // A notch moves model and effort as one; deliver them together when the
      // caller wants the pair, so it never has to read the model back from
      // render props that this handler has not let re-render yet.
      if (onNotchSelect) {
        if (
          model &&
          effort &&
          (model !== currentModel || effort !== currentEffort)
        ) {
          onNotchSelect({ model, effort });
        }
        return;
      }
      if (model && model !== currentModel) changeModel(model);
      if (effort && effort !== currentEffort) onChange?.(effort);
      return;
    }
    if (key !== currentEffort) onChange?.(key);
  };

  const fastSelect =
    fastModeOption?.type === "select" ? fastModeOption : undefined;
  const fastActive = fastSelect?.currentValue === "on";
  // The toggle slot stays mounted across notch drags (its presence depends on
  // the adapter, not the current model) so the popup never reflows; models
  // without fast mode just disable it.
  const fastToggle =
    adapter === "claude" && fastModeFlagEnabled && onConfigOptionChange
      ? {
          active: fastActive,
          disabled: !fastSelect,
          docsUrl: FAST_MODE_DOCS_URLS[adapter],
          onToggle: () => {
            if (fastSelect) {
              onConfigOptionChange(fastSelect.id, fastActive ? "off" : "on");
            }
          },
        }
      : undefined;

  const toggleRows = [contextWindowOption].flatMap((option) => {
    if (!option || option.type !== "select" || !onConfigOptionChange) {
      return [];
    }
    const options = toDropdownOptions(option);
    return [
      {
        id: option.id,
        label: option.name,
        value: option.currentValue,
        valueLabel:
          options.find((entry) => entry.value === option.currentValue)?.label ??
          option.currentValue,
        defaultValue: options.find((entry) => entry.isDefault)?.value,
        options,
      },
    ];
  });

  const selectAndClose = (apply: () => void) => {
    pendingChangeRef.current = apply;
    setOpen(false);
  };

  // Where the built-in reset lands: the ladder's balanced middle notch, or the
  // adapter's default effort for non-ladder pickers. Shared by the reset
  // handler and the disabled check so the two can never disagree.
  const middleStop = stops[Math.floor((stops.length - 1) / 2)];
  const defaultEffortOption = effortOptions.find((option) => option.isDefault);

  const resetToDefaults = () => {
    // One reset for both meanings of "default": drop the pick so the configured
    // project/user default applies where the surface knows about one, else land
    // on the ladder's balanced notch.
    if (onResetToDefault) {
      selectAndClose(onResetToDefault);
      return;
    }
    selectAndClose(() => {
      if (useLadder) {
        const [model, effort] = middleStop?.key.split(STOP_SEPARATOR) ?? [];
        if (model && model !== currentModel) changeModel(model);
        if (effort && effort !== currentEffort) onChange?.(effort);
      } else if (
        defaultEffortOption &&
        defaultEffortOption.value !== currentEffort
      ) {
        onChange?.(defaultEffortOption.value);
      }
      for (const row of toggleRows) {
        if (row.defaultValue && row.defaultValue !== row.value) {
          onConfigOptionChange?.(row.id, row.defaultValue);
        }
      }
      if (fastSelect && fastSelect.currentValue !== "off") {
        onConfigOptionChange?.(fastSelect.id, "off");
      }
    });
  };

  const togglesAtDefault =
    !fastActive &&
    toggleRows.every(
      (row) => !row.defaultValue || row.value === row.defaultValue,
    );
  // Where a configured default exists the caller says whether resetting would
  // change anything; otherwise "default" means where the built-in reset lands.
  const selectionAtDefault = onResetToDefault
    ? (resetToDefaultDisabled ?? false)
    : useLadder
      ? currentStopKey === middleStop?.key
      : currentEffort === defaultEffortOption?.value;

  // Shown on both faces so a deviation is always one click from the default;
  // with nothing to undo, the row is disabled rather than a silent no-op.
  const resetRow = (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuItem
        disabled={selectionAtDefault && togglesAtDefault}
        onClick={resetToDefaults}
      >
        <ArrowCounterClockwise size={12} weight="bold" />
        Reset to default
      </DropdownMenuItem>
    </>
  );

  // Both labels can be blank while a config reloads. The trigger has no icon
  // to fall back on, so it would render as an empty pill announced as
  // "Reasoning: undefined".
  const triggerAriaLabel =
    modelLabel && effortLabel
      ? `Model and reasoning: ${modelLabel} ${effortLabel}`
      : modelLabel
        ? `Model: ${modelLabel}`
        : effortLabel
          ? `Reasoning: ${effortLabel}`
          : "Model and reasoning";

  return (
    <DropdownMenu
      open={open}
      onOpenChange={(nextOpen) => {
        // Only on the closed-to-open transition: submenu opens re-fire this
        // with true and must not yank the view back.
        if (nextOpen && !open) {
          setAdvanced(!onNotch);
          setShowBack(false);
        }
        setOpen(nextOpen);
      }}
      onOpenChangeComplete={(isOpen) => {
        if (!isOpen) {
          setAdvanced(false);
          setShowBack(false);
          if (pendingChangeRef.current !== null) {
            pendingChangeRef.current();
            pendingChangeRef.current = null;
          }
        }
      }}
    >
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="default"
            size="sm"
            disabled={isDisabled}
            aria-label={triggerAriaLabel}
            className={
              fastActive ? "ring-1 ring-amber-9 ring-inset" : undefined
            }
          >
            {fastActive && (
              <span className="text-amber-11">
                <Lightning size={14} weight="fill" />
              </span>
            )}
            {modelLabel && (
              <span className="font-medium text-foreground">
                {isDefaultSelection ? `Default · ${modelLabel}` : modelLabel}
              </span>
            )}
            {effortLabel && (
              <span
                className={
                  modelLabel
                    ? "font-normal text-muted-foreground/80"
                    : undefined
                }
              >
                {effortLabel}
              </span>
            )}
            {!modelLabel && !effortLabel && (
              <span className="font-medium text-foreground">Model</span>
            )}
          </Button>
        }
      />
      <DropdownMenuContent
        align="start"
        side="top"
        sideOffset={6}
        anchor={anchor}
        className="min-w-[230px]"
      >
        <AnimatedHeight>
          <AnimatePresence mode="popLayout" initial={false}>
            {advanced ? (
              <motion.div
                key="advanced"
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.12, ease: "easeOut" }}
              >
                {showBack && <BackRow onClick={() => setAdvanced(false)} />}
                {modelSelect && (
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                      <span>Model</span>
                      <span className="flex-1 text-right text-muted-foreground">
                        {modelLabel}
                      </span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      <ModelSelectList
                        options={modelSelect.options}
                        currentValue={currentModel}
                        onGated={() => setOpen(false)}
                        unavailableReason={unavailableReason}
                        onSelect={(value) => {
                          // A model the current harness cannot run switches
                          // the harness and keeps the pick.
                          if (adapter && onHarnessModelChange) {
                            const entry = modelEntries.find(
                              (candidate) => candidate.value === value,
                            );
                            const harness =
                              selectOptionHarness(entry?._meta) ??
                              adapterForModelId(value);
                            if (harness !== adapter) {
                              onHarnessModelChange(harness, value);
                              return;
                            }
                          }
                          changeModel(value);
                        }}
                      />
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                )}
                {showHarnessSubmenu && adapter && (
                  <HarnessSubmenu
                    value={adapter}
                    includePi={includePiHarness && !!onHarnessChange}
                    closeOnChange={false}
                    onChange={handleHarnessSelect}
                  />
                )}
                {showBillingMenu && adapter && (
                  <SubscriptionSubmenu
                    adapter={adapter}
                    workspaceMode={workspaceMode}
                  />
                )}
                {hasEffort && (
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                      <span>Reasoning</span>
                      <span className="flex-1 text-right text-muted-foreground">
                        {effortLabel}
                      </span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      <DropdownMenuRadioGroup
                        value={currentEffort ?? ""}
                        onValueChange={(value) => onChange?.(value)}
                      >
                        {effortOptions.map((option) => (
                          <LevelItem
                            key={option.value}
                            option={option}
                            closeOnClick={false}
                          />
                        ))}
                      </DropdownMenuRadioGroup>
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                )}
                {toggleRows.map((row) => (
                  <DropdownMenuSub key={row.id}>
                    <DropdownMenuSubTrigger>
                      <span>{row.label}</span>
                      <span className="flex-1 text-right text-muted-foreground">
                        {row.valueLabel}
                      </span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      <DropdownMenuRadioGroup
                        value={row.value}
                        onValueChange={(value) =>
                          onConfigOptionChange?.(row.id, value)
                        }
                      >
                        {row.options.map((option) => (
                          <LevelItem
                            key={option.value}
                            option={option}
                            closeOnClick={false}
                          />
                        ))}
                      </DropdownMenuRadioGroup>
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
                ))}
                {resetRow}
              </motion.div>
            ) : (
              <motion.div
                key="simple"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 8 }}
                transition={{ duration: 0.12, ease: "easeOut" }}
              >
                <ReasoningSliderFace
                  stops={stops}
                  currentKey={currentStopKey}
                  onSelect={handleStopSelect}
                  onAdvanced={() => {
                    setShowBack(true);
                    setAdvanced(true);
                  }}
                  fastToggle={fastToggle}
                />
                {resetRow}
              </motion.div>
            )}
          </AnimatePresence>
        </AnimatedHeight>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
