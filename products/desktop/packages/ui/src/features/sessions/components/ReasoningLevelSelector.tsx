import type {
  SessionConfigOption,
  SessionConfigSelectGroup,
} from "@agentclientprotocol/sdk";
import {
  ArrowCounterClockwise,
  Lightning,
  Spinner,
} from "@phosphor-icons/react";
import {
  getCapabilityLadder,
  getReasoningEffortOptions,
} from "@posthog/agent/adapters/reasoning-effort";
import { compareModelsForPicker } from "@posthog/agent/gateway-models";
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
  FAST_MODE_FLAG,
  isDefaultSelectOption,
  isRestrictedModelOption,
  selectOptionDocsUrl,
} from "@posthog/shared";
import {
  EFFORT_LEVEL_LABELS,
  FAST_MODE_DOCS_URLS,
} from "@posthog/shared/domain-types";
import { gateRestrictedModelPick } from "@posthog/ui/features/billing/modelGate";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import {
  type AgentHarness,
  HarnessSubmenu,
} from "@posthog/ui/features/sessions/components/HarnessSubmenu";
import { ModelCostFooter } from "@posthog/ui/features/sessions/components/ModelCostChip";
import { ModelRadioItem } from "@posthog/ui/features/sessions/components/ModelRadioItem";
import type { AgentAdapter } from "@posthog/ui/features/settings/settingsStore";
import { AnimatedHeight } from "@posthog/ui/primitives/AnimatedHeight";
import { AnimatePresence, motion } from "framer-motion";
import { Fragment, useRef, useState } from "react";
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
  onAdapterChange?: (adapter: AgentAdapter) => void;
  onHarnessChange?: (harness: AgentHarness) => void;
  includePiHarness?: boolean;
  onConfigOptionChange?: (configId: string, value: string) => void;
  menuOpen?: boolean;
  onMenuOpenChange?: (open: boolean) => void;
  disabled?: boolean;
  isLoading?: boolean;
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
  onAdapterChange,
  onHarnessChange,
  includePiHarness,
  onConfigOptionChange,
  menuOpen,
  onMenuOpenChange,
  disabled,
  isLoading,
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

  if (!hasEffort && !modelSelect) {
    if (isLoading) {
      // Keep the dropdown mounted while a harness switch reloads the config:
      // unmounting it here closes a menu the user is mid-interaction with.
      return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
          <DropdownMenuTrigger
            render={
              <Button type="button" variant="default" size="sm">
                <Spinner size={12} className="animate-spin" />
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
            {adapter && (onAdapterChange || onHarnessChange) && (
              <HarnessSubmenu
                value={adapter}
                includePi={includePiHarness && !!onHarnessChange}
                closeOnChange={false}
                onChange={handleHarnessSelect}
              />
            )}
            <DropdownMenuItem disabled>
              <Spinner size={12} className="animate-spin" />
              Loading models...
            </DropdownMenuItem>
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
  const modelGroups =
    modelSelect &&
    modelSelect.options.length > 0 &&
    "group" in modelSelect.options[0]
      ? (modelSelect.options as SessionConfigSelectGroup[])
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

  const resetToDefaults = () => {
    selectAndClose(() => {
      if (useLadder) {
        // The middle notch is the balanced default for the whole ladder.
        const middle = stops[Math.floor((stops.length - 1) / 2)];
        const [model, effort] = middle?.key.split(STOP_SEPARATOR) ?? [];
        if (model && model !== currentModel) changeModel(model);
        if (effort && effort !== currentEffort) onChange?.(effort);
      } else {
        const defaultEffort = effortOptions.find((option) => option.isDefault);
        if (defaultEffort && defaultEffort.value !== currentEffort) {
          onChange?.(defaultEffort.value);
        }
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
              <span className="font-medium text-foreground">{modelLabel}</span>
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
                {adapter && (onAdapterChange || onHarnessChange) && (
                  <HarnessSubmenu
                    value={adapter}
                    includePi={includePiHarness && !!onHarnessChange}
                    closeOnChange={false}
                    onChange={handleHarnessSelect}
                  />
                )}
                {modelSelect && (
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                      <span>Model</span>
                      <span className="flex-1 text-right text-muted-foreground">
                        {modelLabel}
                      </span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      <DropdownMenuRadioGroup
                        value={currentModel ?? ""}
                        onValueChange={(value) => {
                          // A plan-restricted model opens the upgrade gate
                          // instead of becoming the selection.
                          if (gateRestrictedModelPick(modelEntries, value)) {
                            setOpen(false);
                            return;
                          }
                          changeModel(value);
                        }}
                      >
                        {modelGroups.length > 0
                          ? modelGroups.map((group, index) => (
                              <Fragment key={group.group}>
                                {index > 0 && <DropdownMenuSeparator />}
                                {group.options
                                  .toSorted((a, b) =>
                                    compareModelsForPicker(a.value, b.value),
                                  )
                                  .map((model) => (
                                    <ModelRadioItem
                                      key={model.value}
                                      model={model}
                                      closeOnClick={false}
                                    />
                                  ))}
                              </Fragment>
                            ))
                          : modelEntries
                              .toSorted((a, b) =>
                                compareModelsForPicker(a.value, b.value),
                              )
                              .map((model) => (
                                <ModelRadioItem
                                  key={model.value}
                                  model={model}
                                  closeOnClick={false}
                                />
                              ))}
                      </DropdownMenuRadioGroup>
                      <ModelCostFooter />
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
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
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={resetToDefaults}>
                  <ArrowCounterClockwise size={12} weight="bold" />
                  Reset to default
                </DropdownMenuItem>
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
              </motion.div>
            )}
          </AnimatePresence>
        </AnimatedHeight>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
