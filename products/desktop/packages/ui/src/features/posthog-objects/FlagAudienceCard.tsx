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

const HASH_KEY: Record<FlagAudience["bucketing"], string> = {
  person: "the distinct ID",
  device: "the device ID",
  group: "the group key",
};

/** Gutter, conditions, result. The connector line is centered in the gutter. */
const COLUMNS = "grid-cols-[28px_minmax(0,1fr)_auto]";
const CHIP =
  "inline-flex max-w-full items-center gap-1 rounded border border-border bg-card px-1.5 text-xs leading-[18px]";
const PILL =
  "inline-flex h-5 items-center gap-1.5 rounded border border-border bg-card px-1.5 font-semibold text-xs";

function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <Text
      variant="muted"
      className="block font-semibold text-[11px] uppercase tracking-wider"
    >
      {children}
    </Text>
  );
}

function Dot({
  color,
  className = "size-2",
}: {
  color: string;
  className?: string;
}) {
  return (
    <span
      className={`shrink-0 rounded-full ${className}`}
      style={{ background: color }}
    />
  );
}

function SplitBar({
  variants,
  className,
}: {
  variants: FlagVariant[];
  className: string;
}) {
  return (
    <span className={`flex gap-px overflow-hidden rounded-full ${className}`}>
      {variants.map((variant) => (
        <span
          key={variant.key}
          className="h-full"
          title={`${variant.key} · ${variant.percentage}%`}
          style={{
            width: `${variant.percentage}%`,
            background: variantColor(variants, variant.key),
          }}
        />
      ))}
    </span>
  );
}

function ValueChip({ value }: { value: FlagValue }) {
  const link = value.link;
  const evidenceUrl = useEvidenceUrl(link?.kind ?? "person", link?.id ?? "");
  const url = link ? evidenceUrl : null;
  const Icon = link?.kind === "cohort" ? UsersThreeIcon : UserIcon;
  // Narrow panels clip the row, so the chip shrinks with an ellipsis and the
  // hover title carries the full label plus the secondary value.
  const title = [value.label, value.secondary].filter(Boolean).join(" · ");
  const className = `${CHIP} ${link ? "font-medium" : "font-mono"}`;
  const body = (
    <>
      {link && <Icon size={11} className="shrink-0 text-muted-foreground" />}
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
  if (!url) {
    return (
      <span className={className} title={title}>
        {body}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={`${className} cursor-pointer transition-colors hover:bg-muted`}
      title={title}
      onClick={() => openExternalUrl(url)}
    >
      {body}
    </button>
  );
}

function ResultPill({
  result,
  variants,
}: {
  result: FlagResult;
  variants: FlagVariant[];
}) {
  if (result.kind === "split") {
    return (
      <span
        className={PILL}
        title={variants.map((v) => `${v.key} ${v.percentage}%`).join(" · ")}
      >
        <SplitBar variants={variants} className="h-2 w-7" />
        {variants.length} variants
      </span>
    );
  }
  const tone = {
    true: "font-mono text-(--green-11)",
    false: "font-mono text-muted-foreground",
    variant: "font-mono",
    payload: "",
  }[result.kind];
  return (
    <span className={`${PILL} ${tone}`}>
      {result.kind === "variant" && (
        <Dot color={variantColor(variants, result.key)} />
      )}
      {result.kind === "variant" ? result.key : result.kind}
    </span>
  );
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
 * One step of the evaluation flow. Steps are siblings in one list, so CSS
 * trims the connector line at the first and last step.
 */
function Step({
  marker,
  muted,
  result,
  children,
}: {
  marker: ReactNode;
  muted?: boolean;
  result?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      className={`group @container relative grid ${COLUMNS} @max-[560px]:grid-cols-[28px_minmax(0,1fr)] items-center gap-x-3 gap-y-2 px-3 py-3 ${muted ? "text-muted-foreground" : ""}`}
    >
      <span
        aria-hidden
        className="absolute top-0 bottom-0 left-[25px] w-px bg-border group-first:top-1/2 group-last:bottom-1/2"
      />
      <span
        className={`relative z-10 flex size-6 items-center justify-center justify-self-center rounded-full border border-border bg-card font-semibold text-[11px] tabular-nums shadow-xs ${muted ? "border-dashed" : ""}`}
      >
        {marker}
      </span>
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

function RuleStep({
  index,
  rule,
  audience,
}: {
  index: number;
  rule: FlagRule;
  audience: FlagAudience;
}) {
  const everyone = rule.isGroup
    ? "Every group"
    : audience.bucketing === "device"
      ? "Every device"
      : "Everyone";
  return (
    <Step
      marker={index + 1}
      muted={!rule.reachable}
      result={
        <>
          {rule.share < 100 && rule.reachable && (
            <ShareMeter share={rule.share} />
          )}
          <span className={rule.reachable ? "" : "opacity-50"}>
            <ResultPill result={rule.result} variants={audience.variants} />
          </span>
        </>
      }
    >
      {!rule.reachable && (
        <span className="text-[11px]">
          Never reached. An earlier rule already matches everyone.
        </span>
      )}
      {rule.conditions.length === 0 && (
        <span className="font-medium">{everyone}</span>
      )}
      {rule.conditions.map((condition, conditionIndex) => (
        <div
          key={`${condition.subject}:${conditionIndex}`}
          className="flex flex-wrap items-center gap-x-1.5 gap-y-1"
        >
          {conditionIndex > 0 && (
            <span className="text-muted-foreground">and</span>
          )}
          <span className="font-medium text-foreground">
            {condition.subject}
          </span>
          <span className="text-muted-foreground">{condition.operator}</span>
          {condition.values.map((value, valueIndex) => (
            <ValueChip key={`${value.label}:${valueIndex}`} value={value} />
          ))}
        </div>
      ))}
    </Step>
  );
}

/**
 * Answers "who gets this flag, and what do they get?" before showing any
 * structure: a headline, then the rules as a first-match-wins flow where
 * every step ends in its result.
 */
export function FlagAudienceCard({
  audience,
  action,
}: {
  audience: FlagAudience;
  /** Rendered beside the eyebrow; the page passes the edit-in-task control. */
  action?: ReactNode;
}) {
  const { holdout, variants } = audience;
  return (
    <Card size="sm" className="overflow-hidden">
      <CardContent className="p-0">
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3 px-5 py-4">
          <div className="min-w-0 flex-1 basis-64">
            <Eyebrow>Who gets this</Eyebrow>
            <div className="mt-1.5 flex items-start gap-2.5">
              <Dot
                color={audience.disabled ? "var(--gray-8)" : "var(--green-9)"}
                className="mt-2 size-2.5"
              />
              <h2 className="font-semibold text-foreground text-xl leading-tight tracking-tight">
                {audience.headline}
              </h2>
            </div>
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </div>

        {audience.disabled && (
          <div className="flex items-center gap-2.5 border-border border-t bg-muted px-5 py-2.5 text-[12.5px] text-muted-foreground">
            <PowerIcon size={14} className="shrink-0" />
            The flag is off. The rules below apply when the flag is turned on.
          </div>
        )}

        <div
          className={`border-border border-t ${audience.disabled ? "opacity-70" : ""}`}
        >
          <div
            className={`grid ${COLUMNS} gap-x-3 bg-muted px-3 py-1.5 font-medium text-[11px] text-muted-foreground`}
          >
            <span />
            <span>Rules, checked in order. The first match decides.</span>
            <span>Result</span>
          </div>
          <div className="divide-y divide-border">
            {audience.enrollmentKey && (
              <Step
                marker={<KeyIcon size={12} />}
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
              </Step>
            )}
            {holdout && (
              <Step
                marker={<FlaskIcon size={12} />}
                result={
                  <>
                    <ShareMeter share={holdout.exclusionPercentage} />
                    <span className={`${PILL} font-mono`}>
                      holdout-{holdout.id}
                    </span>
                  </>
                }
              >
                <span>
                  <span className="font-medium">Holdout</span>
                  <span className="text-muted-foreground">
                    {" "}
                    for experiment {holdout.id}, decided before the rules
                  </span>
                </span>
              </Step>
            )}
            {audience.rules.map((rule, index) => (
              <RuleStep
                key={`${index}:${rule.conditions.map((c) => c.subject).join("|")}`}
                index={index}
                rule={rule}
                audience={audience}
              />
            ))}
            {audience.rules.length === 0 && (
              <Step marker={null} muted>
                No rules yet. Add a release condition to turn the flag on for
                someone.
              </Step>
            )}
            {audience.fallbackReachable && (
              <Step
                marker={<ArrowElbowDownRightIcon size={12} />}
                muted
                result={
                  <ResultPill result={{ kind: "false" }} variants={variants} />
                }
              >
                Everyone else
              </Step>
            )}
          </div>
        </div>

        {variants.length > 0 && (
          <div className="@container border-border border-t px-5 py-5">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <Eyebrow>Variant split</Eyebrow>
              <Text variant="muted" className="text-xs">
                Assigned by a stable hash of {HASH_KEY[audience.bucketing]}
              </Text>
            </div>
            <SplitBar variants={variants} className="mt-2.5 h-2.5" />
            <div className="mt-3 grid @[560px]:grid-cols-2 gap-x-6 gap-y-2">
              {variants.map((variant) => (
                <div
                  key={variant.key}
                  className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2.5 text-[13px]"
                >
                  <Dot
                    color={variantColor(variants, variant.key)}
                    className="size-2.5"
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
                <span className="font-mono">holdout-{holdout.id}</span> instead
                of a variant.
              </Text>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
