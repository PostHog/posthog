import type {
  SessionConfigOption,
  SessionConfigSelectGroup,
} from "@agentclientprotocol/sdk";
import {
  ArrowCounterClockwise,
  CaretDown,
  Cpu,
  Lightning,
  Robot,
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
  DropdownMenuRadioItem,
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
import { ModelRadioItem } from "@posthog/ui/features/sessions/components/ModelRadioItem";
import type { AgentAdapter } from "@posthog/ui/features/settings/settingsStore";
import { AnimatePresence, motion } from "framer-motion";
import { Fragment, useLayoutEffect, useRef, useState } from "react";
import { flattenSelectOptions } from "../sessionStore";
import { useRetainedConfigOption } from "../useRetainedConfigOption";
import {
  BackRow,
  LevelItem,
  type ReasoningLevelOption,
  ReasoningSliderFace,
} from "./ReasoningLevelDropdown";

const ADAPTER_LABELS: Record<AgentAdapter, string> = {
  claude: "Claude Code",
  codex: "Codex",
};

const ADAPTER_ICONS: Record<AgentAdapter, React.ReactNode> = {
  claude: <Robot size={14} weight="regular" />,
  codex: <Cpu size={14} weight="regular" />,
};

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
  onConfigOptionChange?: (configId: string, value: string) => void;
  disabled?: boolean;
  isLoading?: boolean;
}

/** Tweens the menu's height between the slider and advanced views so the
 * popup morphs instead of snapping when the content swaps. */
function AnimatedHeight({ children }: { children: React.ReactNode }) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number | "auto">("auto");

  useLayoutEffect(() => {
    const node = contentRef.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => setHeight(node.offsetHeight));
    observer.observe(node);
    setHeight(node.offsetHeight);
    return () => observer.disconnect();
  }, []);

  return (
    <motion.div
      initial={false}
      animate={{ height }}
      transition={{ duration: 0.18, ease: [0.3, 0.9, 0.3, 1] }}
      className="overflow-hidden"
    >
      <div ref={contentRef}>{children}</div>
    </motion.div>
  );
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
  onConfigOptionChange,
  disabled,
  isLoading,
}: ReasoningLevelSelectorProps) {
  const [open, setOpen] = useState(false);
  const [advanced, setAdvanced] = useState(false);
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

  if (!hasEffort && !modelSelect) {
    if (isLoading) {
      return (
        <Button type="button" variant="default" size="sm" disabled>
          <Spinner size={12} className="animate-spin" />
          Loading...
        </Button>
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

  const triggerAriaLabel =
    modelLabel && effortLabel
      ? `Model and reasoning: ${modelLabel} ${effortLabel}`
      : modelLabel
        ? `Model: ${modelLabel}`
        : `Reasoning: ${effortLabel}`;

  return (
    <DropdownMenu
      open={open}
      onOpenChange={(nextOpen) => {
        // Only on the closed-to-open transition: submenu opens re-fire this
        // with true and must not yank the view back.
        if (nextOpen && !open) setAdvanced(!onNotch);
        setOpen(nextOpen);
      }}
      onOpenChangeComplete={(isOpen) => {
        if (!isOpen) {
          setAdvanced(false);
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
            {fastActive ? (
              <span className="text-amber-11">
                <Lightning size={14} weight="fill" />
              </span>
            ) : (
              adapter && (
                <span className="text-muted-foreground">
                  {ADAPTER_ICONS[adapter]}
                </span>
              )
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
                {onNotch && <BackRow onClick={() => setAdvanced(false)} />}
                {onAdapterChange && adapter && (
                  <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                      <span>Harness</span>
                      <span className="flex-1 text-right text-muted-foreground">
                        {ADAPTER_LABELS[adapter]}
                      </span>
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent>
                      <DropdownMenuRadioGroup
                        value={adapter}
                        onValueChange={(value) => {
                          if (value !== adapter) {
                            selectAndClose(() =>
                              onAdapterChange(value as AgentAdapter),
                            );
                          }
                        }}
                      >
                        <DropdownMenuRadioItem value="claude">
                          Claude Code
                        </DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value="codex">
                          Codex
                        </DropdownMenuRadioItem>
                      </DropdownMenuRadioGroup>
                    </DropdownMenuSubContent>
                  </DropdownMenuSub>
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
                          selectAndClose(() => changeModel(value));
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
                                />
                              ))}
                      </DropdownMenuRadioGroup>
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
                        onValueChange={(value) =>
                          selectAndClose(() => onChange?.(value))
                        }
                      >
                        {effortOptions.map((option) => (
                          <LevelItem key={option.value} option={option} />
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
                          selectAndClose(() =>
                            onConfigOptionChange?.(row.id, value),
                          )
                        }
                      >
                        {row.options.map((option) => (
                          <LevelItem key={option.value} option={option} />
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
                  onAdvanced={() => setAdvanced(true)}
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
