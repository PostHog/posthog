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

function EntityChip({ value }: { value: FlagValue }) {
  const link = value.link;
  const url = useEvidenceUrl(link?.kind ?? "person", link?.id ?? "");
  const body = (
    <>
      <span>{value.label}</span>
      {value.secondary && (
        <span className="font-normal text-muted-foreground">
          {value.secondary}
        </span>
      )}
      {url && <span className="text-[10px] opacity-70">↗</span>}
    </>
  );
  const className =
    "inline-flex items-center gap-1.5 rounded-md border border-(--blue-6) bg-(--blue-2) px-2 py-px font-medium text-(--blue-11) text-xs leading-5";
  if (!url) {
    return (
      <span className={className} title={value.raw}>
        {body}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={`${className} cursor-pointer hover:bg-(--blue-3)`}
      title={value.raw}
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
      className={`inline-flex items-center rounded-md border border-border bg-muted px-2 py-px text-xs leading-5 ${value.literal ? "font-mono" : "font-medium"}`}
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
    <div className="flex flex-wrap items-center gap-1.5">
      {!first && (
        <span className="font-semibold text-[10.5px] text-muted-foreground uppercase tracking-wide">
          and
        </span>
      )}
      <span className="text-muted-foreground">
        {condition.subject} {condition.operator}
      </span>
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
    "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 font-semibold text-xs";
  switch (result.kind) {
    case "true":
      return (
        <span
          className={`${base} border-(--green-6) bg-(--green-2) font-mono text-(--green-11)`}
        >
          true
        </span>
      );
    case "false":
      return (
        <span
          className={`${base} border-border bg-muted font-mono text-muted-foreground`}
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
        <span className={`${base} border-border bg-card text-foreground`}>
          <span
            className="size-2 rounded-full"
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
          <span className="flex gap-0.5">
            {variants.map((variant) => (
              <span
                key={variant.key}
                className="size-2 rounded-full"
                style={{ background: variantColor(variants, variant.key) }}
              />
            ))}
          </span>
          a variant
        </span>
      );
  }
}

function RuleRow({
  index,
  rule,
  variants,
}: {
  index: number;
  rule: FlagRule;
  variants: FlagVariant[];
}) {
  return (
    <div className="grid grid-cols-[22px_1fr_auto] items-center gap-x-3 border-border border-b px-3 py-2.5 last:border-b-0">
      <span className="flex size-5 items-center justify-center rounded-md border border-border bg-muted font-semibold text-[11px] text-foreground">
        {index + 1}
      </span>
      <div className="flex min-w-0 flex-col gap-1 text-[13px]">
        {rule.conditions.length === 0 ? (
          <span>Everyone</span>
        ) : (
          rule.conditions.map((condition, conditionIndex) => (
            <ConditionLine
              key={`${condition.subject}:${conditionIndex}`}
              condition={condition}
              first={conditionIndex === 0}
            />
          ))
        )}
      </div>
      <div className="flex items-center justify-end gap-2.5 whitespace-nowrap">
        {rule.share < 100 && (
          <span className="text-[11px] text-muted-foreground tabular-nums">
            {rule.share}% of matches
          </span>
        )}
        <ResultPill result={rule.result} variants={variants} />
      </div>
    </div>
  );
}

function VariantsList({ variants }: { variants: FlagVariant[] }) {
  return (
    <div className="mt-4">
      <div className="flex items-baseline justify-between gap-2">
        <Text
          variant="muted"
          className="block text-[11px] uppercase tracking-wider"
        >
          Variants
        </Text>
        <Text variant="muted" className="text-xs">
          Assigned by a stable hash, so a person keeps their variant
        </Text>
      </div>
      <div className="mt-2 flex h-2 gap-0.5 overflow-hidden rounded">
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
      </div>
      {variants.map((variant) => (
        <div
          key={variant.key}
          className="grid grid-cols-[auto_1fr_auto] items-center gap-3 border-border border-b py-1.5 text-[13px] last:border-b-0"
        >
          <span className="flex items-center gap-2">
            <span
              className="size-2 rounded-full"
              style={{ background: variantColor(variants, variant.key) }}
            />
            <span className="font-mono font-semibold text-xs">
              {variant.key}
            </span>
          </span>
          <span
            className={`truncate font-mono text-xs ${variant.payload ? "text-foreground" : "text-muted-foreground"}`}
          >
            {variant.payload ?? "No payload"}
          </span>
          <span className="font-semibold tabular-nums">
            {variant.percentage}%
          </span>
        </div>
      ))}
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

/**
 * Answers "who gets this flag, and what do they get?" before showing any
 * structure: a headline, one outcome sentence, then the rules as a
 * first-match-wins table where every row ends in its result.
 */
export function FlagAudienceCard({ audience }: { audience: FlagAudience }) {
  // A rule with no conditions at 100% matches everyone, so nobody reaches the fallback.
  const fallbackReachable = !audience.rules.some(
    (rule) => rule.conditions.length === 0 && rule.share === 100,
  );
  return (
    <Card size="sm">
      <CardContent>
        <Text
          variant="muted"
          className="block text-[11px] uppercase tracking-wider"
        >
          Who gets this
        </Text>
        <div className="mt-2 font-semibold text-base text-foreground tracking-tight">
          {audience.headline}
        </div>
        <Text className="mt-0.5 block text-[13px] text-muted-foreground">
          {audience.summary}
        </Text>

        <div
          className={`mt-3.5 overflow-hidden rounded-lg border border-border ${audience.disabled ? "opacity-60" : ""}`}
        >
          <div className="flex justify-between border-border border-b bg-muted px-3 py-1.5 text-[11px] text-muted-foreground">
            <span>Rules, checked in order. First match wins.</span>
            <span>Result</span>
          </div>
          {audience.rules.map((rule, index) => (
            <RuleRow
              key={ruleKey(rule, index)}
              index={index}
              rule={rule}
              variants={audience.variants}
            />
          ))}
          {fallbackReachable && (
            <div className="grid grid-cols-[22px_1fr_auto] items-center gap-x-3 px-3 py-2.5 text-[13px] text-muted-foreground">
              <span />
              <span>Everyone else</span>
              <ResultPill
                result={audience.fallback}
                variants={audience.variants}
              />
            </div>
          )}
        </div>

        {audience.variants.length > 0 && (
          <VariantsList variants={audience.variants} />
        )}
      </CardContent>
    </Card>
  );
}
