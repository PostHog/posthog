import {
  ArrowElbowDownRightIcon,
  ArrowSquareOutIcon,
  FlaskIcon,
  KeyIcon,
  PowerIcon,
  UserIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import type {
  FlagAudience,
  FlagCondition,
  FlagResult,
  FlagRule,
  FlagValue,
  FlagVariant,
} from "@posthog/api-client/flag-audience";
import { Card, CardContent, Text } from "@posthog/quill";
import { useEvidenceUrl } from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import type { ReactNode } from "react";

const VARIANT_COLORS = [
  "var(--primary)",
  "var(--blue-9)",
  "var(--teal-9)",
  "var(--purple-9)",
  "var(--amber-9)",
  "var(--pink-9)",
];

function variantColor(variants: FlagVariant[], key: string): string {
  const index = variants.findIndex((variant) => variant.key === key);
  return VARIANT_COLORS[Math.max(index, 0) % VARIANT_COLORS.length];
}

/** The width of the step gutter; the connector line is centered in it. */
const GUTTER = "grid-cols-[28px_minmax(0,1fr)_auto]";

function EntityChip({ value }: { value: FlagValue }) {
  const link = value.link;
  const url = useEvidenceUrl(link?.kind ?? "person", link?.id ?? "");
  const Icon = link?.kind === "cohort" ? UsersThreeIcon : UserIcon;
  // Narrow panels clip the row, so the chip shrinks with an ellipsis and the
  // hover title carries the full label plus the secondary value.
  const title = [value.label, value.secondary].filter(Boolean).join(" · ");
  const body = (
    <>
      <Icon size={12} className="shrink-0 text-muted-foreground" />
      <span className="min-w-0 truncate">{value.label}</span>
      {value.secondary && (
        <span className="min-w-0 truncate font-normal text-muted-foreground">
          {value.secondary}
        </span>
      )}
      {url && (
        <ArrowSquareOutIcon
          size={11}
          className="shrink-0 text-muted-foreground"
        />
      )}
    </>
  );
  const className =
    "inline-flex max-w-full items-center gap-1.5 rounded-md border border-border bg-card px-1.5 py-px font-medium text-foreground text-xs leading-5";
  if (!url) {
    return (
      <span className={className} title={title || value.raw}>
        {body}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={`${className} cursor-pointer transition-colors hover:bg-muted`}
      title={title || value.raw}
      onClick={() => openExternalUrl(url)}
    >
      {body}
    </button>
  );
}

function ValueChip({ value }: { value: FlagValue }) {
  if (value.link) return <EntityChip value={value} />;
  return (
    <span
      className={`inline-flex max-w-full items-center truncate rounded-md border border-border bg-card px-1.5 py-px text-xs leading-5 ${value.literal ? "font-mono" : "font-medium"}`}
      title={value.label}
    >
      {value.label}
    </span>
  );
}

function ConditionLine({
  condition,
  first,
}: {
  condition: FlagCondition;
  first: boolean;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
      {!first && <span className="text-muted-foreground">and</span>}
      <span className="font-medium text-foreground">{condition.subject}</span>
      <span className="text-muted-foreground">{condition.operator}</span>
      {condition.values.map((value, index) => (
        <ValueChip key={`${value.label}:${index}`} value={value} />
      ))}
    </div>
  );
}

function ResultPill({
  result,
  variants,
}: {
  result: FlagResult;
  variants: FlagVariant[];
}) {
  const base =
    "inline-flex h-6 items-center gap-1.5 rounded-md border px-2 font-semibold text-xs";
  switch (result.kind) {
    case "true":
      return (
        <span
          className={`${base} border-border bg-card font-mono text-(--green-11)`}
        >
          true
        </span>
      );
    case "false":
      return (
        <span
          className={`${base} border-border bg-card font-mono text-muted-foreground`}
        >
          false
        </span>
      );
    case "payload":
      return (
        <span className={`${base} border-border bg-card text-foreground`}>
          payload
        </span>
      );
    case "variant":
      return (
        <span
          className={`${base} border-border bg-card font-mono text-foreground`}
        >
          <span
            className="size-2 shrink-0 rounded-full"
            style={{ background: variantColor(variants, result.key) }}
          />
          {result.key}
        </span>
      );
    case "split":
      return (
        <span
          className={`${base} border-border bg-card text-foreground`}
          title={variants
            .map((variant) => `${variant.key} ${variant.percentage}%`)
            .join(" · ")}
        >
          <span className="flex h-2 w-7 gap-px overflow-hidden rounded-full">
            {variants.map((variant) => (
              <span
                key={variant.key}
                className="h-full"
                style={{
                  width: `${variant.percentage}%`,
                  background: variantColor(variants, variant.key),
                }}
              />
            ))}
          </span>
          {variants.length} variants
        </span>
      );
  }
}

/** A tiny meter next to a partial rollout, so the share is read at a glance. */
function ShareMeter({ share }: { share: number }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground tabular-nums"
      title={`${share}% of the people who match this rule`}
    >
      <span className="flex h-1.5 w-10 overflow-hidden rounded-full bg-border">
        <span
          className="h-full rounded-full bg-muted-foreground"
          style={{ width: `${share}%` }}
        />
      </span>
      {share}% of matches
    </span>
  );
}

/**
 * One row of the evaluation flow. The gutter draws the connector line and a
 * marker; `position` trims the line at the top and bottom of the flow.
 */
function FlowRow({
  marker,
  position,
  muted,
  children,
  result,
}: {
  marker: ReactNode;
  position: "first" | "middle" | "last" | "only";
  muted?: boolean;
  children: ReactNode;
  result?: ReactNode;
}) {
  const lineTop =
    position === "first" || position === "only" ? "top-1/2" : "top-0";
  const lineBottom =
    position === "last" || position === "only" ? "bottom-1/2" : "bottom-0";
  return (
    <div
      className={`@container relative grid ${GUTTER} @max-[560px]:grid-cols-[28px_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-3 py-3 ${muted ? "text-muted-foreground" : ""}`}
    >
      <span
        aria-hidden
        className={`absolute left-[25px] ${lineTop} ${lineBottom} w-px bg-border`}
      />
      <span className="relative z-10 flex justify-center">{marker}</span>
      <div className="flex min-w-0 flex-col gap-1.5 text-[13px]">
        {children}
      </div>
      {result && (
        <div className="@max-[560px]:col-start-2 flex items-center @max-[560px]:justify-start justify-end gap-3 whitespace-nowrap">
          {result}
        </div>
      )}
    </div>
  );
}

function StepMarker({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "muted";
}) {
  const tones = {
    default: "border-border bg-card text-foreground",
    muted: "border-dashed border-border bg-card text-muted-foreground",
  };
  return (
    <span
      className={`flex size-6 items-center justify-center rounded-full border font-semibold text-[11px] tabular-nums shadow-xs ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

function RuleRow({
  index,
  rule,
  variants,
  bucketing,
  position,
}: {
  index: number;
  rule: FlagRule;
  variants: FlagVariant[];
  bucketing: FlagAudience["bucketing"];
  position: "first" | "middle" | "last" | "only";
}) {
  const unreachable = rule.reachable === false;
  const everyone = rule.isGroup
    ? "Every group"
    : bucketing === "device_id"
      ? "Every device"
      : "Everyone";
  return (
    <FlowRow
      marker={
        <StepMarker tone={unreachable ? "muted" : "default"}>
          {index + 1}
        </StepMarker>
      }
      position={position}
      muted={unreachable}
      result={
        <>
          {rule.share < 100 && !unreachable && (
            <ShareMeter share={rule.share} />
          )}
          <span className={unreachable ? "opacity-50" : ""}>
            <ResultPill result={rule.result} variants={variants} />
          </span>
        </>
      }
    >
      {unreachable && (
        <span className="text-[11px] text-muted-foreground">
          Never reached. An earlier rule already matches everyone.
        </span>
      )}
      {rule.conditions.length === 0 ? (
        <span className="font-medium">{everyone}</span>
      ) : (
        rule.conditions.map((condition, conditionIndex) => (
          <ConditionLine
            key={`${condition.subject}:${conditionIndex}`}
            condition={condition}
            first={conditionIndex === 0}
          />
        ))
      )}
    </FlowRow>
  );
}

function VariantsSection({
  variants,
  stability,
  holdout,
}: {
  variants: FlagVariant[];
  stability: FlagAudience["stability"];
  holdout: FlagAudience["holdout"];
}) {
  return (
    <div className="mt-5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <Text
          variant="muted"
          className="block font-semibold text-[11px] uppercase tracking-wider"
        >
          Variant split
        </Text>
        <Text variant="muted" className="text-xs">
          Assigned by a stable hash of {stability}
        </Text>
      </div>
      <div className="mt-2.5 flex h-2.5 gap-0.5 overflow-hidden rounded-full">
        {variants.map((variant) => (
          <span
            key={variant.key}
            className="h-full first:rounded-l-full last:rounded-r-full"
            title={`${variant.key} · ${variant.percentage}%`}
            style={{
              width: `${variant.percentage}%`,
              background: variantColor(variants, variant.key),
            }}
          />
        ))}
      </div>
      <div className="mt-3 grid @[560px]:grid-cols-2 gap-x-6 gap-y-2">
        {variants.map((variant) => (
          <div
            key={variant.key}
            className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2.5 text-[13px]"
          >
            <span
              className="size-2.5 rounded-full"
              style={{ background: variantColor(variants, variant.key) }}
            />
            <span className="flex min-w-0 items-baseline gap-2">
              <span className="font-mono font-semibold text-xs">
                {variant.key}
              </span>
              {variant.payload && (
                <code
                  title={variant.payload}
                  className="min-w-0 truncate rounded bg-muted px-1 font-mono text-[11px] text-muted-foreground"
                >
                  {variant.payload}
                </code>
              )}
            </span>
            <span className="font-semibold tabular-nums">
              {variant.percentage}%
            </span>
          </div>
        ))}
      </div>
      {holdout && (
        <Text variant="muted" className="mt-2.5 block text-xs">
          {holdout.exclusionPercentage}% of people receive{" "}
          <span className="font-mono">holdout-{holdout.id}</span> instead of a
          variant.
        </Text>
      )}
    </div>
  );
}

/** Rules have no id; conditions plus position keep keys stable across refetches. */
function ruleKey(rule: FlagRule, index: number): string {
  const conditions = rule.conditions
    .map((condition) => `${condition.subject} ${condition.operator}`)
    .join("|");
  return `${index}:${conditions}`;
}

function flowPosition(
  index: number,
  total: number,
): "first" | "middle" | "last" | "only" {
  if (total === 1) return "only";
  if (index === 0) return "first";
  if (index === total - 1) return "last";
  return "middle";
}

/**
 * Answers "who gets this flag, and what do they get?" before showing any
 * structure: a headline, one outcome sentence, then the rules as a
 * first-match-wins flow where every step ends in its result.
 */
export function FlagAudienceCard({
  audience,
  action,
}: {
  audience: FlagAudience;
  /** Rendered beside the eyebrow; the page passes the edit-in-task control. */
  action?: ReactNode;
}) {
  // Pre-checks and the fallback are steps in the same flow as the rules, so
  // they share one index space for the connector line.
  const preChecks = [
    audience.enrollmentKey ? "enrollment" : null,
    audience.holdout ? "holdout" : null,
  ].filter((step): step is "enrollment" | "holdout" => step !== null);
  const stepCount =
    preChecks.length +
    audience.rules.length +
    (audience.fallbackReachable ? 1 : 0);
  let step = 0;
  const nextPosition = () => flowPosition(step++, stepCount);

  return (
    <Card size="sm" className="overflow-hidden">
      <CardContent className="p-0">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-5 pt-4 pb-4">
          <div className="min-w-0 flex-1 basis-64">
            <Text
              variant="muted"
              className="block font-semibold text-[11px] uppercase tracking-wider"
            >
              Who gets this
            </Text>
            <div className="mt-1.5 flex items-start gap-2.5">
              <span
                aria-hidden
                className={`mt-2 size-2.5 shrink-0 rounded-full ${
                  audience.disabled ? "bg-(--gray-8)" : "bg-(--green-9)"
                }`}
              />
              <h2 className="font-semibold text-foreground text-xl leading-tight tracking-tight">
                {audience.headline}
              </h2>
            </div>
            <Text className="mt-1.5 block max-w-prose text-[13px] text-muted-foreground leading-relaxed">
              {audience.summary}
            </Text>
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>

        {audience.disabled && (
          <div className="flex items-center gap-2.5 border-border border-t bg-muted px-5 py-2.5 text-[12.5px] text-muted-foreground">
            <PowerIcon size={14} className="shrink-0" />
            <span>
              The flag is off. The rules below apply when the flag is turned on.
            </span>
          </div>
        )}

        <div
          className={`border-border border-t ${audience.disabled ? "opacity-70" : ""}`}
        >
          <div
            className={`grid ${GUTTER} gap-x-3 bg-muted px-3 py-1.5 font-medium text-[11px] text-muted-foreground`}
          >
            <span />
            <span>Rules, checked in order. The first match decides.</span>
            <span>Result</span>
          </div>
          <div className="divide-y divide-border">
            {audience.enrollmentKey && (
              <FlowRow
                marker={
                  <StepMarker>
                    <KeyIcon size={12} />
                  </StepMarker>
                }
                position={nextPosition()}
                result={
                  <span className="text-[11px] text-muted-foreground">
                    true → true, anything else → false
                  </span>
                }
              >
                <span>
                  <span className="font-medium">Early access</span>
                  <span className="text-muted-foreground">
                    {" "}
                    checks the{" "}
                    <code className="rounded bg-muted px-1 font-mono text-[12px] text-foreground">
                      {audience.enrollmentKey}
                    </code>{" "}
                    person property first
                  </span>
                </span>
              </FlowRow>
            )}
            {audience.holdout && (
              <FlowRow
                marker={
                  <StepMarker>
                    <FlaskIcon size={12} />
                  </StepMarker>
                }
                position={nextPosition()}
                result={
                  <>
                    <ShareMeter share={audience.holdout.exclusionPercentage} />
                    <span className="inline-flex h-6 items-center rounded-md border border-border bg-card px-2 font-mono font-semibold text-xs">
                      holdout-{audience.holdout.id}
                    </span>
                  </>
                }
              >
                <span>
                  <span className="font-medium">Holdout</span>
                  <span className="text-muted-foreground">
                    {" "}
                    for experiment {audience.holdout.id}, decided before the
                    rules
                  </span>
                </span>
              </FlowRow>
            )}
            {audience.rules.map((rule, index) => (
              <RuleRow
                key={ruleKey(rule, index)}
                index={index}
                rule={rule}
                variants={audience.variants}
                bucketing={audience.bucketing}
                position={nextPosition()}
              />
            ))}
            {audience.rules.length === 0 && (
              <div
                className={`grid ${GUTTER} gap-x-3 px-3 py-3 text-[13px] text-muted-foreground`}
              >
                <span />
                <span>
                  No rules yet. Add a release condition to turn the flag on for
                  someone.
                </span>
              </div>
            )}
            {audience.fallbackReachable && (
              <FlowRow
                marker={
                  <StepMarker tone="muted">
                    <ArrowElbowDownRightIcon size={12} />
                  </StepMarker>
                }
                position={nextPosition()}
                muted
                result={
                  <ResultPill
                    result={audience.fallback}
                    variants={audience.variants}
                  />
                }
              >
                <span>Everyone else</span>
              </FlowRow>
            )}
          </div>
        </div>

        {audience.variants.length > 0 && (
          <div className="@container border-border border-t px-5 pb-5">
            <VariantsSection
              variants={audience.variants}
              stability={audience.stability}
              holdout={audience.holdout}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
