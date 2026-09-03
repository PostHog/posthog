import { InfoIcon } from "@phosphor-icons/react";
import type { ExperimentVariantResultPresentation } from "@posthog/api-client/evidence-previews";
import { Text, Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import type { ReactElement } from "react";

const EDGE_MARGIN_PERCENT = 3;

function toPercent(value: number, axisRange: number): number {
  const clamped = Math.max(-axisRange, Math.min(axisRange, value));
  const fraction = (clamped / axisRange + 1) / 2;
  return EDGE_MARGIN_PERCENT + fraction * (100 - 2 * EDGE_MARGIN_PERCENT);
}

function deltaTicks(axisRange: number): number[] {
  const max = Math.ceil(axisRange * 10) / 10;
  const magnitude = Math.floor(Math.log10(max));
  const power = 10 ** magnitude;
  const normalized = max / power;
  const unit =
    normalized <= 1
      ? 0.2 * power
      : normalized <= 2
        ? 0.5 * power
        : normalized <= 5
          ? power
          : 2 * power;
  const limit = max * 0.9;
  const steps = Math.ceil(limit / unit);
  const decimals = Math.max(0, -magnitude + 1);
  const ticks: number[] = [];
  for (let step = -steps; step <= steps; step++) {
    const value = Number((unit * step).toFixed(decimals));
    if (Math.abs(value) <= limit) ticks.push(value);
  }
  return ticks;
}

function labelledTicks(axisRange: number): number[] {
  const ticks = deltaTicks(axisRange);
  if (ticks.length <= 7) return ticks;
  const zero = ticks.indexOf(0);
  return ticks.filter((_, index) => Math.abs(index - zero) % 2 === 0);
}

function formatTick(value: number): string {
  const percent = value * 100;
  if (percent === 0) return "0";
  const rounded =
    Math.abs(percent) < 1 ? percent.toFixed(1) : String(Math.round(percent));
  return `${percent > 0 ? "+" : ""}${rounded}%`;
}

function GridLines({ axisRange }: { axisRange: number }): ReactElement {
  return (
    <>
      {deltaTicks(axisRange).map((tick) => (
        <span
          key={tick}
          className={`absolute inset-y-0 w-px ${tick === 0 ? "bg-muted-foreground/50" : "bg-border/70"}`}
          style={{ left: `${toPercent(tick, axisRange)}%` }}
        />
      ))}
    </>
  );
}

export function ExperimentDeltaAxis({
  axisRange,
}: {
  axisRange: number;
}): ReactElement {
  return (
    <div className="w-full min-w-48">
      <Tooltip>
        <TooltipTrigger
          render={
            <span className="mb-1 flex items-center gap-1 font-normal text-muted-foreground">
              Uplift vs baseline
              <InfoIcon size={12} />
            </span>
          }
        />
        <TooltipContent className="max-w-70" side="top">
          Each bar covers the range the true uplift is likely to fall in. A bar
          that crosses the zero line is not significant yet.
        </TooltipContent>
      </Tooltip>
      <div className="relative h-3.5 w-full">
        {labelledTicks(axisRange).map((tick) => (
          <span
            key={tick}
            className={`-translate-x-1/2 absolute top-0 font-normal text-[10px] tabular-nums ${tick === 0 ? "text-muted-foreground" : "text-muted-foreground/70"}`}
            style={{ left: `${toPercent(tick, axisRange)}%` }}
          >
            {formatTick(tick)}
          </span>
        ))}
      </div>
    </div>
  );
}

function TooltipRow({
  label,
  value,
}: {
  label: string;
  value: string;
}): ReactElement {
  return (
    <span className="flex items-baseline justify-between gap-4">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular-nums">{value}</span>
    </span>
  );
}

export function ExperimentDeltaBar({
  variant,
  axisRange,
}: {
  variant: ExperimentVariantResultPresentation;
  axisRange: number;
}): ReactElement {
  const bounds = variant.intervalBounds;
  const significant = variant.significance === "significant";
  const tone =
    significant && variant.isImprovement === true
      ? "bg-success-foreground"
      : significant && variant.isImprovement === false
        ? "bg-destructive-foreground"
        : "bg-muted-foreground";
  const left = bounds ? toPercent(bounds[0], axisRange) : 0;
  const right = bounds ? toPercent(bounds[1], axisRange) : 0;

  const track = (
    <div className="group/delta relative h-7 w-full min-w-48">
      <GridLines axisRange={axisRange} />
      {!variant.isControl && bounds && (
        <>
          <span
            className={`-translate-y-1/2 absolute top-1/2 h-[3px] rounded-full opacity-40 transition-opacity group-hover/delta:opacity-70 ${tone}`}
            style={{
              left: `${left}%`,
              width: `${Math.max(right - left, 0.4)}%`,
            }}
          />
          {[left, right].map((edge, index) => (
            <span
              key={index === 0 ? "lower" : "upper"}
              className={`-translate-x-1/2 -translate-y-1/2 absolute top-1/2 h-2 w-[2px] rounded-full opacity-50 transition-opacity group-hover/delta:opacity-80 ${tone}`}
              style={{ left: `${edge}%` }}
            />
          ))}
          {variant.upliftValue !== null && (
            <span
              className={`-translate-x-1/2 -translate-y-1/2 absolute top-1/2 size-2.5 rounded-full ring-2 ring-card ${tone}`}
              style={{
                left: `${toPercent(variant.upliftValue, axisRange)}%`,
              }}
            />
          )}
        </>
      )}
      {!variant.isControl && !bounds && (
        <Text
          render={<span />}
          size="xxs"
          variant="muted"
          className="-translate-y-1/2 absolute top-1/2 left-0"
        >
          Not enough data yet
        </Text>
      )}
    </div>
  );

  if (variant.isControl || !bounds) return track;
  return (
    <Tooltip>
      <TooltipTrigger render={track} />
      <TooltipContent className="flex-col items-stretch gap-0.5" side="top">
        <span className="font-medium">{variant.key}</span>
        {variant.uplift && <TooltipRow label="Uplift" value={variant.uplift} />}
        {variant.interval && (
          <TooltipRow label="95% interval" value={variant.interval} />
        )}
        {variant.pValue && (
          <TooltipRow label="p-value" value={variant.pValue} />
        )}
        {variant.chanceToWin && (
          <TooltipRow label="Chance to win" value={variant.chanceToWin} />
        )}
      </TooltipContent>
    </Tooltip>
  );
}
