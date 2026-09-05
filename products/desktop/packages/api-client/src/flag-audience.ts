import type { Schemas } from "./generated";

/**
 * Who a feature flag reaches, shaped for reading rather than editing: a
 * headline sentence, the rules as a first-match-wins table where every row
 * ends in its result, and the variant split when the flag has one.
 */
export interface FlagAudience {
  /** "On for one person." */
  headline: string;
  /** "Alex gets true. Everyone else gets false." */
  summary: string;
  disabled: boolean;
  rules: FlagRule[];
  /** What a check returns when no rule matches. */
  fallback: FlagResult;
  /** False when a reachable rule already matches everyone, so the fallback row is hidden. */
  fallbackReachable: boolean;
  variants: FlagVariant[];
  /** What a check buckets on, which decides the variant-assignment hash key. */
  bucketing: "distinct_id" | "device_id";
  /** The bucketing key as display text: "the distinct ID", "the device ID", "the group key". */
  stability: string;
  /** Person property checked before the rules for early access flags; null when off. */
  enrollmentKey: string | null;
  /** Experiment holdout checked before the rules; null when the flag has none. */
  holdout: { id: string; exclusionPercentage: number } | null;
}

export interface FlagRule {
  /** Empty when the rule matches everyone. */
  conditions: FlagCondition[];
  /** Rollout percentage within the matched audience. */
  share: number;
  result: FlagResult;
  /** False when an earlier catch-all for the same aggregation shadows this rule. */
  reachable: boolean;
  /** True when the rule aggregates over groups instead of persons. */
  isGroup: boolean;
}

export type FlagResult =
  | { kind: "true" }
  | { kind: "false" }
  | { kind: "variant"; key: string }
  | { kind: "split" }
  | { kind: "payload" };

export interface FlagCondition {
  /** "Person", "Group", "email", "Cohort", "Flag" */
  subject: string;
  /** "is", "in cohort", "ends with" */
  operator: string;
  values: FlagValue[];
}

export interface FlagValue {
  label: string;
  /** Email under a resolved person, for example. */
  secondary?: string;
  /** The raw id behind a resolved label. */
  raw?: string;
  link?: { kind: "person" | "cohort"; id: string };
  literal: boolean;
}

export interface FlagVariant {
  key: string;
  percentage: number;
  payload: string | null;
}

export interface ResolvedPerson {
  uuid: string;
  name: string;
  email: string | null;
}

// Typed against the generated operator union so a new schema operator fails
// the typecheck here instead of leaking its raw token into the card.
const OPERATORS: Record<Schemas.PropertyOperator, string> = {
  exact: "is",
  is_not: "is not",
  icontains: "contains",
  not_icontains: "does not contain",
  icontains_multi: "contains any of",
  not_icontains_multi: "does not contain any of",
  between: "is between",
  not_between: "is not between",
  regex: "matches",
  not_regex: "does not match",
  starts_with: "starts with",
  not_starts_with: "does not start with",
  ends_with: "ends with",
  not_ends_with: "does not end with",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  is_set: "is set",
  is_not_set: "is not set",
  in: "in cohort",
  not_in: "not in cohort",
  flag_evaluates_to: "evaluates to",
  is_date_before: "before",
  is_date_after: "after",
  is_date_exact: "on",
  semver_eq: "is version",
  semver_neq: "is not version",
  semver_gt: "newer than",
  semver_gte: "at least version",
  semver_lt: "older than",
  semver_lte: "at most version",
  semver_tilde: "is version in tilde range",
  semver_caret: "is version in caret range",
  semver_wildcard: "matches version wildcard",
  is_cleaned_path_exact: "is cleaned path",
  min: "at least once ≥",
  max: "at most once ≤",
};

type Property = Record<string, unknown>;

function isRecord(value: unknown): value is Property {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | null {
  if (typeof value === "string" && value) return value;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return String(value);
  return null;
}

function isDistinctIdFilter(property: Property): boolean {
  return property.type === "person" && property.key === "distinct_id";
}

/** Distinct ids a flag targets directly, so the caller can resolve them to people. */
export function targetedDistinctIds(flag: Schemas.FeatureFlag): string[] {
  return collectDistinctIds(flag, () => true);
}

/**
 * Distinct ids a flag positively targets, so the caller can label them as
 * targeted. Excludes negative conditions such as `is not`, whose ids the rule
 * rejects; person-name resolution still uses the full list.
 */
export function positivelyTargetedDistinctIds(
  flag: Schemas.FeatureFlag,
): string[] {
  return collectDistinctIds(
    flag,
    (operator) => operator === undefined || operator === "exact",
  );
}

function collectDistinctIds(
  flag: Schemas.FeatureFlag,
  include: (operator: string | undefined) => boolean,
): string[] {
  const groups = conditionGroups(flag);
  const ids = new Set<string>();
  for (const group of groups) {
    for (const property of group.properties) {
      if (!isDistinctIdFilter(property)) continue;
      const operator = asString(property.operator) ?? undefined;
      if (!include(operator)) continue;
      const values = Array.isArray(property.value)
        ? property.value
        : [property.value];
      for (const value of values) {
        const id = asString(value);
        if (id) ids.add(id);
      }
    }
  }
  return [...ids];
}

interface ConditionGroup {
  properties: Property[];
  rollout: number;
  variant: string | null;
  isGroup: boolean;
  /** The resolved aggregation index: a number for group targeting, null for person. */
  aggregationIndex: number | null;
}

function conditionGroups(flag: Schemas.FeatureFlag): ConditionGroup[] {
  const filters = isRecord(flag.filters) ? flag.filters : {};
  const groups = Array.isArray(filters.groups) ? filters.groups : [];
  const flagLevelGroupIndex = filters.aggregation_group_type_index;
  return groups.filter(isRecord).map((group) => {
    const rollout =
      typeof group.rollout_percentage === "number"
        ? group.rollout_percentage
        : 100;
    // An explicit null means person-level aggregation; only an absent field
    // inherits the flag-level group index. `??` would collapse that null into
    // the flag-level value and mislabel person rules as group rules.
    const groupIndex =
      group.aggregation_group_type_index !== undefined
        ? group.aggregation_group_type_index
        : flagLevelGroupIndex;
    return {
      properties: Array.isArray(group.properties)
        ? group.properties.filter(isRecord)
        : [],
      rollout,
      variant: asString(group.variant),
      isGroup: typeof groupIndex === "number",
      aggregationIndex: typeof groupIndex === "number" ? groupIndex : null,
    };
  });
}

function shapeValues(
  property: Property,
  people: Map<string, ResolvedPerson>,
): FlagValue[] {
  if (property.type === "cohort") {
    const id = asString(property.value) ?? "";
    const name = asString(property.cohort_name);
    return [
      {
        label: name ?? `Cohort ${id}`,
        raw: name ? id : undefined,
        link: id ? { kind: "cohort", id } : undefined,
        literal: false,
      },
    ];
  }
  const raw = Array.isArray(property.value)
    ? property.value
    : property.value === undefined || property.value === null
      ? []
      : [property.value];
  const distinctId = isDistinctIdFilter(property);
  return raw.flatMap((entry): FlagValue[] => {
    const value = asString(entry);
    if (!value) return [];
    if (distinctId) {
      const person = people.get(value);
      if (person) {
        return [
          {
            label: person.name,
            secondary:
              person.email && person.email !== person.name
                ? person.email
                : undefined,
            raw: value,
            link: { kind: "person", id: person.uuid },
            literal: false,
          },
        ];
      }
      return [{ label: value, literal: true }];
    }
    return [{ label: value, literal: true }];
  });
}

function shapeCondition(
  property: Property,
  isGroup: boolean,
  people: Map<string, ResolvedPerson>,
): FlagCondition | null {
  const operatorKey = asString(property.operator);
  const values = shapeValues(property, people);
  if (property.type === "cohort") {
    return {
      subject: isGroup ? "Group" : "Person",
      operator: OPERATORS[(operatorKey ?? "in") as Schemas.PropertyOperator] ?? "in cohort",
      values,
    };
  }
  if (property.type === "flag") {
    return {
      subject: "Flag",
      operator: OPERATORS.flag_evaluates_to,
      values: [
        { label: asString(property.key) ?? "", literal: true },
        ...values,
      ],
    };
  }
  if (isDistinctIdFilter(property)) {
    return {
      subject: "Person",
      operator: OPERATORS[(operatorKey ?? "exact") as Schemas.PropertyOperator] ?? "is",
      values,
    };
  }
  const key = asString(property.key);
  if (!key) return null;
  return {
    subject: key,
    operator:
      OPERATORS[(operatorKey ?? "exact") as Schemas.PropertyOperator] ??
      operatorKey ??
      "is",
    values,
  };
}

interface Audience {
  /** "one person", "25% of Power users" */
  label: string;
  plural: boolean;
  /** Replaces the default "<label> gets <result>." sentence when the label alone misreads. */
  sentence?: string;
}

function describeAudience(
  rule: FlagRule,
  group: ConditionGroup,
  people: Map<string, ResolvedPerson>,
  deviceBucketed: boolean,
): Audience {
  const noun = group.isGroup ? "groups" : "people";
  const share = rule.share < 100 ? `${rule.share}% of ` : "";
  if (rule.conditions.length === 0) {
    if (rule.share < 100) {
      return { label: `${rule.share}% of ${noun}`, plural: true };
    }
    // A group rule still needs a group key, and a device-bucketed rule still
    // needs a device ID, so "everyone" would overstate who matches.
    if (rule.isGroup) {
      return { label: "every group", plural: true };
    }
    if (deviceBucketed) {
      return { label: "every device", plural: true };
    }
    // "everyone" takes a singular verb in the summary sentence.
    return { label: "everyone", plural: false };
  }
  if (rule.conditions.length === 1 && group.properties.length === 1) {
    const [condition] = rule.conditions;
    const [property] = group.properties;
    if (
      property &&
      isDistinctIdFilter(property) &&
      condition.operator === "is"
    ) {
      const n = condition.values.length;
      if (n === 1) {
        const person = people.get(condition.values[0].raw ?? "");
        const who = person ? person.name : "one person";
        // The rollout is a per-identifier hash: a named person is either in
        // or out, never a fraction, so the share stays on the rule row.
        return {
          label: who,
          plural: false,
          sentence:
            rule.share < 100
              ? `${who} is targeted, and the ${rule.share}% rollout hash decides.`
              : undefined,
        };
      }
      return { label: `${share}${n} people`, plural: true };
    }
    if (property?.type === "cohort" && condition.operator === "in cohort") {
      return {
        label: `${share}${condition.values[0]?.label ?? "a cohort"}`,
        plural: true,
      };
    }
  }
  const conditions =
    rule.conditions.length === 1
      ? "one condition"
      : `${rule.conditions.length} conditions`;
  return { label: `${share}${noun} matching ${conditions}`, plural: true };
}

function describeResult(result: FlagResult): string {
  switch (result.kind) {
    case "true":
      return "true";
    case "false":
      return "false";
    case "variant":
      return result.key;
    case "split":
      return "a variant";
    case "payload":
      return "the payload";
  }
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function joinAudiences(labels: string[]): string {
  if (labels.length <= 1) return labels[0] ?? "everyone";
  if (labels.length === 2) return `${labels[0]} and ${labels[1]}`;
  return `${labels.length} audiences`;
}

/**
 * A reachable rule with no conditions at 100% matches every evaluable check,
 * leaving nobody for the fallback. Group rules still need a group key and
 * device-bucketed rules still need a device ID, so those keep the fallback.
 */
function catchAllRule(rule: FlagRule, deviceBucketed: boolean): boolean {
  return (
    rule.reachable &&
    rule.conditions.length === 0 &&
    rule.share === 100 &&
    !rule.isGroup &&
    !deviceBucketed
  );
}

export function shapeFlagAudience(
  flag: Schemas.FeatureFlag,
  people: Map<string, ResolvedPerson> = new Map(),
): FlagAudience {
  const filters = isRecord(flag.filters) ? flag.filters : {};
  const multivariate = isRecord(filters.multivariate)
    ? filters.multivariate
    : null;
  const payloads = isRecord(filters.payloads) ? filters.payloads : {};
  const variants: FlagVariant[] = Array.isArray(multivariate?.variants)
    ? multivariate.variants.filter(isRecord).flatMap((variant) => {
        const key = asString(variant.key);
        if (!key) return [];
        return [
          {
            key,
            percentage:
              typeof variant.rollout_percentage === "number"
                ? variant.rollout_percentage
                : 0,
            payload: asString(payloads[key]),
          },
        ];
      })
    : [];
  const isRemoteConfig = flag.is_remote_configuration === true;
  const disabled = flag.active === false;
  const groups = conditionGroups(flag);
  const deviceBucketed = filters.bucketing_identifier === "device_id";
  // The variant hash key follows the bucketing identifier: device id when set,
  // the group key for group-aggregated rules, otherwise the distinct ID.
  const stability = deviceBucketed
    ? "the device ID"
    : groups.some((group) => group.isGroup)
      ? "the group key"
      : "the distinct ID";
  const bucketing: FlagAudience["bucketing"] = deviceBucketed
    ? "device_id"
    : "distinct_id";

  const matchResult = (variant: string | null): FlagResult => {
    if (isRemoteConfig) return { kind: "payload" };
    if (variant) return { kind: "variant", key: variant };
    if (variants.length > 0) return { kind: "split" };
    return { kind: "true" };
  };

  const holdoutRecord = isRecord(filters.holdout) ? filters.holdout : null;
  const holdout: FlagAudience["holdout"] = holdoutRecord
    ? {
        id: asString(holdoutRecord.id) ?? "",
        exclusionPercentage: Math.min(
          Math.max(
            typeof holdoutRecord.exclusion_percentage === "number"
              ? holdoutRecord.exclusion_percentage
              : 0,
            0,
          ),
          100,
        ),
      }
    : null;

  // Early access flags check the enrollment person property before any rule:
  // a true value returns true immediately, any other present value returns
  // false, and an absent value falls through to the rules below.
  const enrollmentKey =
    filters.feature_enrollment === true
      ? `$feature_enrollment/${flag.key}`
      : null;

  const rules: FlagRule[] = groups.map((group) => ({
    conditions: group.properties.flatMap((property) => {
      const condition = shapeCondition(property, group.isGroup, people);
      return condition ? [condition] : [];
    }),
    share: group.rollout,
    result: matchResult(group.variant),
    reachable: true,
    isGroup: group.isGroup,
  }));
  // The evaluator checks condition sets in declaration order and returns on
  // the first match, so an empty condition set at 100% shadows every later
  // set of the same aggregation. Mirrors the web flag page's own warning.
  const shadowedAggregations = new Set<string>();
  groups.forEach((group, index) => {
    const aggregation =
      typeof group.aggregationIndex === "number"
        ? `group:${group.aggregationIndex}`
        : "person";
    if (shadowedAggregations.has(aggregation)) {
      rules[index].reachable = false;
      return;
    }
    if (rules[index].conditions.length === 0 && group.rollout >= 100) {
      shadowedAggregations.add(aggregation);
    }
  });
  const fallback: FlagResult = { kind: "false" };

  if (disabled) {
    return {
      headline: "Off for everyone.",
      summary: "The flag is disabled, so every check returns false.",
      disabled,
      rules,
      fallback,
      fallbackReachable: !rules.some((rule) => catchAllRule(rule, deviceBucketed)),
      variants,
      bucketing,
      stability,
      enrollmentKey,
      holdout,
    };
  }

  if (rules.length === 0) {
    // The evaluator skips the condition loop on empty groups and returns
    // false, so clearing targeting turns the flag off for everybody.
    return {
      headline: isRemoteConfig
        ? "Sends a payload to nobody."
        : "On for nobody.",
      summary:
        "The flag has no release conditions, so every check returns false.",
      disabled,
      rules,
      fallback,
      fallbackReachable: true,
      variants,
      bucketing,
      stability,
      enrollmentKey,
      holdout,
    };
  }

  const live = rules.filter((rule) => rule.share > 0 && rule.reachable);
  if (live.length === 0) {
    return {
      headline: "On for nobody yet.",
      summary:
        "Rules are defined, but rollout is 0%, so every check returns false.",
      disabled,
      rules,
      fallback,
      fallbackReachable: true,
      variants,
      bucketing,
      stability,
      enrollmentKey,
      holdout,
    };
  }

  const audiences = live.map((rule) =>
    describeAudience(
      rule,
      groups[rules.indexOf(rule)],
      people,
      deviceBucketed,
    ),
  );
  const who = joinAudiences(audiences.map((audience) => audience.label));
  const headline = isRemoteConfig
    ? `Sends a payload to ${who}.`
    : variants.length > 0
      ? `Split into ${variants.length} variants for ${who}.`
      : `On for ${who}.`;

  const sentences = live.slice(0, 2).map((rule, index) => {
    const audience = audiences[index];
    if (audience.sentence) return audience.sentence;
    return `${capitalize(audience.label)} ${audience.plural ? "get" : "gets"} ${describeResult(rule.result)}.`;
  });
  if (live.length > 2) {
    const more = live.length - 2;
    sentences.push(
      `${more} more ${more === 1 ? "rule applies" : "rules apply"}.`,
    );
  }
  const fallbackReachable = !rules.some((rule) =>
    catchAllRule(rule, deviceBucketed),
  );
  // The evaluator resolves enrollment and the holdout before the rules, so
  // those sentences come first.
  const overrideSentences: string[] = [];
  if (enrollmentKey) {
    overrideSentences.push(
      `${enrollmentKey} overrides these rules: a true value always gets true, and any other value gets false.`,
    );
  } else if (holdout) {
    overrideSentences.push(
      `${holdout.exclusionPercentage}% of people are held out for experiment ${holdout.id} and get holdout-${holdout.id}.`,
    );
  }
  const allSentences = [...overrideSentences, ...sentences];
  if (fallbackReachable && !enrollmentKey) {
    allSentences.push(
      deviceBucketed || rules.some((rule) => rule.isGroup)
        ? "A check without its bucketing key still gets false."
        : "Everyone else gets false.",
    );
  }

  return {
    headline,
    summary: allSentences.join(" "),
    disabled,
    rules,
    fallback,
    fallbackReachable,
    variants,
    bucketing,
    stability,
    enrollmentKey,
    holdout,
  };
}

/** Short "Reach" label for the stat strip: "1 person", "25% of a cohort", "Everyone". */
export function flagReachLabel(audience: FlagAudience): string {
  if (audience.disabled) return "Nobody";
  const match = audience.headline.match(/(?:for|to) (.+)\.$/);
  if (!match) return "Everyone";
  return capitalize(match[1]);
}
