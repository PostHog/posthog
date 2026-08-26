import {
  Brain,
  CaretDown,
  CaretLeft,
  CaretRight,
  Lightning,
  Question,
} from "@phosphor-icons/react";
import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  MenuLabel,
  Slider,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { Badge } from "@posthog/ui/primitives/Badge";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { Fragment, useRef, useState } from "react";

export interface ReasoningLevelOption {
  value: string;
  label: string;
  description?: string;
  isDefault?: boolean;
  docsUrl?: string;
}

export interface ReasoningMenuSection {
  key: string;
  label: string;
  value: string;
  options: ReasoningLevelOption[];
  onChange: (value: string) => void;
}

export interface ReasoningSliderStop {
  key: string;
  label: string;
}

interface ReasoningLevelDropdownProps {
  value: string;
  options: ReasoningLevelOption[];
  onChange?: (value: string) => void;
  sections?: ReasoningMenuSection[];
  disabled?: boolean;
  label?: string;
  side?: "top" | "bottom";
  /**
   * "slider" opens on a Faster/Smarter slider with an Advanced view holding
   * the full lists. "list" opens straight on the lists (form-style pickers
   * whose options include sentinels).
   */
  variant?: "slider" | "list";
  triggerVariant?: "default" | "outline";
  triggerClassName?: string;
}

/**
 * The shared reasoning dropdown for standalone effort pickers (loops,
 * settings, autoresearch, agent config, Pi). Session and composer surfaces
 * render the merged model + reasoning control in ReasoningLevelSelector,
 * which builds on the same slider face and items exported here.
 */
export function ReasoningLevelDropdown({
  value,
  options,
  onChange,
  sections,
  disabled,
  label = "Reasoning",
  side = "top",
  variant = "list",
  triggerVariant = "default",
  triggerClassName,
}: ReasoningLevelDropdownProps) {
  const [open, setOpen] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const pendingChangeRef = useRef<(() => void) | null>(null);

  if (options.length === 0) return null;

  const activeLabel =
    options.find((option) => option.value === value)?.label ?? value;

  const selectAndClose = (apply: () => void) => {
    pendingChangeRef.current = apply;
    setOpen(false);
  };

  const lists = (
    <>
      <MenuLabel>{label}</MenuLabel>
      <DropdownMenuRadioGroup
        value={value}
        onValueChange={(next) => selectAndClose(() => onChange?.(next))}
      >
        {options.map((option) => (
          <LevelItem key={option.value} option={option} />
        ))}
      </DropdownMenuRadioGroup>
      {sections?.map((section) => (
        <Fragment key={section.key}>
          <DropdownMenuSeparator />
          <MenuLabel>{section.label}</MenuLabel>
          <DropdownMenuRadioGroup
            value={section.value}
            onValueChange={(next) =>
              selectAndClose(() => section.onChange(next))
            }
          >
            {section.options.map((option) => (
              <LevelItem key={option.value} option={option} />
            ))}
          </DropdownMenuRadioGroup>
        </Fragment>
      ))}
    </>
  );

  return (
    <DropdownMenu
      open={open}
      onOpenChange={setOpen}
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
            variant={triggerVariant}
            size="sm"
            disabled={disabled}
            aria-label={`${label}: ${activeLabel}`}
            className={triggerClassName}
          >
            <Brain size={14} className="text-muted-foreground" />
            {activeLabel}
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
        side={side}
        sideOffset={6}
        className="min-w-[220px]"
      >
        {variant === "list" ? (
          lists
        ) : advanced ? (
          <>
            <BackRow onClick={() => setAdvanced(false)} />
            {lists}
          </>
        ) : (
          <ReasoningSliderFace
            stops={options.map((option) => ({
              key: option.value,
              label: option.label,
            }))}
            currentKey={value}
            onSelect={(key) => {
              if (key !== value) onChange?.(key);
            }}
            onAdvanced={() => setAdvanced(true)}
          />
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function BackRow({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      className="flex w-full items-center gap-1 px-2 py-1.5 text-muted-foreground text-xs hover:text-foreground"
      onClick={onClick}
    >
      <CaretLeft size={10} weight="bold" />
      Back
    </button>
  );
}

/**
 * The Faster/Smarter slider face: an Advanced link (and optional fast-mode
 * lightning toggle) above a notched slider whose stops the caller defines.
 */
export function ReasoningSliderFace({
  stops,
  currentKey,
  onSelect,
  onAdvanced,
  fastToggle,
}: {
  stops: ReasoningSliderStop[];
  currentKey?: string;
  onSelect: (key: string) => void;
  onAdvanced: () => void;
  fastToggle?: {
    active: boolean;
    disabled?: boolean;
    docsUrl?: string;
    onToggle: () => void;
  };
}) {
  const matchedIndex = stops.findIndex((stop) => stop.key === currentKey);
  const activeIndex =
    matchedIndex >= 0 ? matchedIndex : Math.floor((stops.length - 1) / 2);
  // Continuous drag position so the thumb tracks the pointer fluidly; outside
  // a drag the thumb derives from the current selection, so releasing snaps
  // it to the notch the live-applied selection landed on.
  const [dragPosition, setDragPosition] = useState<number | null>(null);
  const position = dragPosition ?? activeIndex;
  const nearestIndex = Math.min(
    stops.length - 1,
    Math.max(0, Math.round(position)),
  );

  const applyNotch = (notch: number) => {
    const stop = stops[notch];
    if (stop && stop.key !== currentKey) onSelect(stop.key);
  };

  const nudge = (delta: number) => {
    const next = Math.min(stops.length - 1, Math.max(0, nearestIndex + delta));
    setDragPosition(null);
    applyNotch(next);
  };

  return (
    <div className="flex min-w-[220px] flex-col gap-2 p-2">
      <div className="flex items-center justify-between">
        <button
          type="button"
          className="flex items-center gap-1 text-muted-foreground text-xs hover:text-foreground"
          onClick={onAdvanced}
        >
          Advanced
          <CaretRight size={10} weight="bold" />
        </button>
        {fastToggle && (
          <span
            className={cn(
              "flex items-center gap-1.5",
              // Hidden, not unmounted: the slot keeps its size so sliding
              // across models never reflows the popup.
              fastToggle.disabled && "invisible",
            )}
          >
            <TooltipProvider delay={300}>
              <Tooltip>
                <TooltipTrigger
                  render={
                    <button
                      type="button"
                      aria-label="Toggle fast mode"
                      aria-pressed={fastToggle.active}
                      disabled={fastToggle.disabled}
                      className={cn(
                        "rounded-md border border-border p-1.5",
                        fastToggle.active
                          ? "text-amber-11"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                      onClick={fastToggle.onToggle}
                    >
                      <Lightning
                        size={13}
                        weight={fastToggle.active ? "fill" : "regular"}
                      />
                    </button>
                  }
                />
                <TooltipContent className="border border-(--gray-6) bg-(--gray-2)! text-foreground! [&_.quill-tooltip\_\_arrow]:hidden">
                  <span className="flex flex-col items-center gap-0.5 text-center">
                    <span>Fast Mode ({fastToggle.active ? "ON" : "OFF"})</span>
                    {fastToggle.docsUrl && (
                      <button
                        type="button"
                        className="text-muted-foreground underline hover:text-foreground"
                        onClick={() => {
                          if (fastToggle.docsUrl) {
                            void openUrlInBrowser(fastToggle.docsUrl);
                          }
                        }}
                      >
                        Learn more
                      </button>
                    )}
                  </span>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </span>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 text-muted-foreground/60 text-xs">
        <span>Faster ($)</span>
        <span>Smarter ($$$)</span>
      </div>
      <div
        className="relative py-1"
        onKeyDownCapture={(event) => {
          if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
            event.preventDefault();
            event.stopPropagation();
            nudge(-1);
          } else if (event.key === "ArrowRight" || event.key === "ArrowUp") {
            event.preventDefault();
            event.stopPropagation();
            nudge(1);
          }
        }}
      >
        <Slider
          aria-label="Reasoning level"
          min={0}
          max={stops.length - 1}
          step={0.01}
          value={[position]}
          onValueChange={(next: number | readonly number[]) => {
            const raw = Array.isArray(next) ? next[0] : next;
            if (typeof raw !== "number") return;
            setDragPosition(raw);
            // Applied per notch crossing so the trigger pill tracks the drag.
            applyNotch(Math.round(raw));
          }}
          onValueCommitted={(next: number | readonly number[]) => {
            const raw = Array.isArray(next) ? next[0] : next;
            if (typeof raw === "number") {
              applyNotch(
                Math.min(stops.length - 1, Math.max(0, Math.round(raw))),
              );
            }
            setDragPosition(null);
          }}
        />
        <div className="-translate-y-1/2 pointer-events-none absolute inset-x-2 top-1/2 flex justify-between">
          {stops.map((stop, stopIndex) => (
            <span
              key={stop.key}
              className={cn(
                "size-1 rounded-full",
                stopIndex <= nearestIndex
                  ? "bg-background/80"
                  : "bg-foreground/30",
              )}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function LevelItem({
  option,
  closeOnClick,
}: {
  option: ReasoningLevelOption;
  closeOnClick?: boolean;
}) {
  return (
    <DropdownMenuRadioItem value={option.value} closeOnClick={closeOnClick}>
      <span className="flex min-w-0 flex-col">
        <span className="whitespace-nowrap">{option.label}</span>
        {option.description && (
          <span className="text-muted-foreground text-xs">
            {option.description}
          </span>
        )}
      </span>
      {(option.isDefault || option.docsUrl) && (
        <span className="ml-auto flex items-center gap-1.5 pl-3">
          {option.isDefault && <Badge color="gray">Default</Badge>}
          {option.docsUrl && (
            <DocsLink label={option.label} docsUrl={option.docsUrl} />
          )}
        </span>
      )}
    </DropdownMenuRadioItem>
  );
}

// A span with button semantics: menu items render as real <button>s, and
// nesting a second button inside one is invalid HTML.
function DocsLink({ label, docsUrl }: { label: string; docsUrl: string }) {
  const openDocs = (event: React.SyntheticEvent) => {
    event.preventDefault();
    event.stopPropagation();
    void openUrlInBrowser(docsUrl);
  };
  return (
    // biome-ignore lint/a11y/useSemanticElements: a real <button> can't nest inside the menu item's <button>
    <span
      role="button"
      tabIndex={-1}
      aria-label={`Learn more about ${label}`}
      className="text-muted-foreground hover:text-foreground"
      onPointerDown={(event) => event.stopPropagation()}
      onPointerUp={(event) => event.stopPropagation()}
      onClick={openDocs}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") openDocs(event);
      }}
    >
      <Question size={14} />
    </span>
  );
}
