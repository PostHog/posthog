import type { Schemas } from "./generated";

/**
 * Who a feature flag reaches, shaped for reading rather than editing: a
 * headline, the rules as a first-match-wins list where every row ends in
 * its result, and the variant split when the flag has one.
 */
export interface FlagAudience {
  /** "On for one person." */
  headline: string;
  disabled: boolean;
  rules: FlagRule[];
  /** False when a reachable rule already matches everyone, so the "Everyone else" row is hidden. */
  fallbackReachable: boolean;
  variants: FlagVariant[];
  /** What the evaluator hashes on for rollouts and variant assignment. */
  bucketing: "person" | "device" | "group";
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
  /** Set when the value is a person or cohort the card can open; absent for literals. */
  link?: { kind: "person" | "cohort"; id: string };
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

/** A flag or anything that carries flag filters, such as a survey's targeting flag. */
export type FlagLike = Pick<
  Schemas.FeatureFlag,
  "key" | "filters" | "active" | "is_remote_configuration"
>;

/** Headline verbs; a survey is "shown to" people, a flag is "on for" them. */
export interface AudienceWording {
  on: string;
  off: string;
}

const FLAG_WORDING: AudienceWording = {
  on: "On for",
  off: "Off for everyone.",
};

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
type People = Map<string, ResolvedPerson>;

function isRecord(value: unknown): value is Property {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | null {
  if (typeof value === "string") return value || null;
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  if (typeof value === "boolean") return String(value);
  return null;
}

function asList(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  return value === undefined || value === null ? [] : [value];
}

function isDistinctIdFilter(property: Property): boolean {
  return property.type === "person" && property.key === "distinct_id";
}

function operatorLabel(
  operator: unknown,
  fallback: Schemas.PropertyOperator,
): string {
  const key = asString(operator);
  return OPERATORS[(key ?? fallback) as Schemas.PropertyOperator] ?? key ?? "";
}

interface ConditionGroup {
  properties: Property[];
  rollout: number;
  variant: string | null;
  isGroup: boolean;
  /** "person" or "group:<index>"; rules only shadow later rules of the same aggregation. */
  aggregation: string;
}

function conditionGroups(flag: FlagLike): ConditionGroup[] {
  const filters = isRecord(flag.filters) ? flag.filters : {};
  return asList(filters.groups)
    .filter(isRecord)
    .map((group) => {
      // An explicit null means person-level aggregation; only an absent field
      // inherits the flag-level group index.
      const index =
        group.aggregation_group_type_index !== undefined
          ? group.aggregation_group_type_index
          : filters.aggregation_group_type_index;
      const isGroup = typeof index === "number";
      return {
        properties: asList(group.properties).filter(isRecord),
        rollout:
          typeof group.rollout_percentage === "number"
            ? group.rollout_percentage
            : 100,
        variant: asString(group.variant),
        isGroup,
        aggregation: isGroup ? `group:${index}` : "person",
      };
    });
}

/**
 * Distinct ids a flag targets, so the caller can resolve them to people.
 * `positiveOnly` drops negative operators such as `is not`, whose ids the
 * rule rejects rather than targets.
 */
export function targetedDistinctIds(
  flag: FlagLike,
  positiveOnly = false,
): string[] {
  const ids = new Set<string>();
  for (const group of conditionGroups(flag)) {
    for (const property of group.properties) {
      if (!isDistinctIdFilter(property)) continue;
      const operator = property.operator;
      if (positiveOnly && operator !== undefined && operator !== "exact") {
        continue;
      }
      for (const value of asList(property.value)) {
        const id = asString(value);
        if (id) ids.add(id);
      }
    }
  }
  return [...ids];
}

function shapeCondition(
  property: Property,
  isGroup: boolean,
  people: People,
): FlagCondition | null {
  if (property.type === "cohort") {
    const id = asString(property.value) ?? "";
    const name = asString(property.cohort_name);
    return {
      subject: isGroup ? "Group" : "Person",
      operator: operatorLabel(property.operator, "in"),
      values: [
        {
          label: name ?? `Cohort ${id}`,
          raw: id,
          link: id ? { kind: "cohort", id } : undefined,
        },
      ],
    };
  }
  const distinctId = isDistinctIdFilter(property);
  const values = asList(property.value).flatMap((entry): FlagValue[] => {
    const value = asString(entry);
    if (!value) return [];
    const person = distinctId ? people.get(value) : undefined;
    if (!person) return [{ label: value }];
    return [
      {
        label: person.name,
        secondary:
          person.email && person.email !== person.name
            ? person.email
            : undefined,
        raw: value,
        link: { kind: "person", id: person.uuid },
      },
    ];
  });
  if (property.type === "flag") {
    return {
      subject: "Flag",
      operator: OPERATORS.flag_evaluates_to,
      values: [{ label: asString(property.key) ?? "" }, ...values],
    };
  }
  const operator = operatorLabel(property.operator, "exact");
  if (distinctId) return { subject: "Person", operator, values };
  const key = asString(property.key);
  return key ? { subject: key, operator, values } : null;
}

function describeAudience(
  rule: FlagRule,
  group: ConditionGroup,
  people: People,
  bucketing: FlagAudience["bucketing"],
): string {
  const share = rule.share < 100 ? `${rule.share}% of ` : "";
  const noun = group.isGroup ? "groups" : "people";
  if (rule.conditions.length === 0) {
    if (share) return `${share}${noun}`;
    // A group rule still needs a group key, and a device-bucketed rule still
    // needs a device ID, so "everyone" would overstate who matches.
    if (group.isGroup) return "every group";
    return bucketing === "device" ? "every device" : "everyone";
  }
  const [condition] = rule.conditions;
  const [property] = group.properties;
  if (rule.conditions.length === 1 && group.properties.length === 1) {
    if (isDistinctIdFilter(property) && condition.operator === "is") {
      const count = condition.values.length;
      if (count > 1) return `${share}${count} people`;
      // The rollout hashes the identifier: a named person is either in or
      // out, never a fraction, so the share stays on the rule row.
      return people.get(condition.values[0]?.raw ?? "")?.name ?? "one person";
    }
    if (property.type === "cohort" && condition.operator === "in cohort") {
      return `${share}${condition.values[0]?.label ?? "a cohort"}`;
    }
  }
  const count =
    rule.conditions.length === 1
      ? "one condition"
      : `${rule.conditions.length} conditions`;
  return `${share}${noun} matching ${count}`;
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

type Shape = Omit<FlagAudience, "headline">;

function headlineFor(
  shape: Shape,
  groups: ConditionGroup[],
  people: People,
  remoteConfig: boolean,
  wording: AudienceWording,
): string {
  if (shape.disabled) return wording.off;
  // The evaluator skips the condition loop on empty groups and returns false,
  // so clearing targeting turns the flag off for everybody.
  if (shape.rules.length === 0) {
    return remoteConfig
      ? "Sends a payload to nobody."
      : `${wording.on} nobody.`;
  }
  const live = shape.rules.filter((rule) => rule.share > 0 && rule.reachable);
  if (live.length === 0) return `${wording.on} nobody yet.`;
  const labels = live.map((rule) =>
    describeAudience(
      rule,
      groups[shape.rules.indexOf(rule)],
      people,
      shape.bucketing,
    ),
  );
  const who =
    labels.length === 1
      ? labels[0]
      : labels.length === 2
        ? `${labels[0]} and ${labels[1]}`
        : `${labels.length} audiences`;
  if (remoteConfig) return `Sends a payload to ${who}.`;
  if (shape.variants.length > 0) {
    return `Split into ${shape.variants.length} variants for ${who}.`;
  }
  return `${wording.on} ${who}.`;
}

export function shapeFlagAudience(
  flag: FlagLike,
  people: People = new Map(),
  wording: AudienceWording = FLAG_WORDING,
): FlagAudience {
  const filters = isRecord(flag.filters) ? flag.filters : {};
  const payloads = isRecord(filters.payloads) ? filters.payloads : {};
  const multivariate = isRecord(filters.multivariate)
    ? filters.multivariate
    : {};
  const variants = asList(multivariate.variants)
    .filter(isRecord)
    .flatMap((variant): FlagVariant[] => {
      const key = asString(variant.key);
      if (!key) return [];
      const percentage = variant.rollout_percentage;
      return [
        {
          key,
          percentage: typeof percentage === "number" ? percentage : 0,
          payload: asString(payloads[key]),
        },
      ];
    });
  const remoteConfig = flag.is_remote_configuration === true;
  const groups = conditionGroups(flag);
  const deviceBucketed = filters.bucketing_identifier === "device_id";
  const bucketing: FlagAudience["bucketing"] = deviceBucketed
    ? "device"
    : groups.some((group) => group.isGroup)
      ? "group"
      : "person";
  const resultFor = (variant: string | null): FlagResult => {
    if (remoteConfig) return { kind: "payload" };
    if (variant) return { kind: "variant", key: variant };
    return variants.length > 0 ? { kind: "split" } : { kind: "true" };
  };

  // The evaluator checks condition sets in order and returns on the first
  // match, so an empty set at 100% shadows every later set of the same
  // aggregation. Mirrors the web flag page's own warning.
  const shadowed = new Set<string>();
  const rules = groups.map((group): FlagRule => {
    const reachable = !shadowed.has(group.aggregation);
    const conditions = group.properties.flatMap(
      (property) => shapeCondition(property, group.isGroup, people) ?? [],
    );
    if (conditions.length === 0 && group.rollout >= 100) {
      shadowed.add(group.aggregation);
    }
    return {
      conditions,
      share: group.rollout,
      result: resultFor(group.variant),
      reachable,
      isGroup: group.isGroup,
    };
  });
  // A reachable catch-all leaves nobody for the fallback. Group rules still
  // need a group key and device-bucketed rules a device ID, so those keep it.
  const catchAll =
    !deviceBucketed &&
    rules.some(
      (rule) =>
        rule.reachable &&
        !rule.isGroup &&
        rule.conditions.length === 0 &&
        rule.share === 100,
    );

  const holdoutRecord = isRecord(filters.holdout) ? filters.holdout : null;
  const exclusion = holdoutRecord?.exclusion_percentage;
  const shape: Shape = {
    disabled: flag.active === false,
    rules,
    fallbackReachable: !catchAll,
    variants,
    bucketing,
    // Early access flags check the enrollment person property before any
    // rule: true returns true, any other present value returns false.
    enrollmentKey:
      filters.feature_enrollment === true
        ? `$feature_enrollment/${flag.key}`
        : null,
    holdout: holdoutRecord
      ? {
          id: asString(holdoutRecord.id) ?? "",
          exclusionPercentage: Math.min(
            Math.max(typeof exclusion === "number" ? exclusion : 0, 0),
            100,
          ),
        }
      : null,
  };
  return {
    ...shape,
    headline: headlineFor(shape, groups, people, remoteConfig, wording),
  };
}

/** Short "Reach" label for the stat strip: "1 person", "25% of a cohort", "Everyone". */
export function flagReachLabel(audience: FlagAudience): string {
  if (audience.disabled) return "Nobody";
  const match = audience.headline.match(/(?:for|to) (.+)\.$/);
  return match ? capitalize(match[1]) : "Everyone";
}
