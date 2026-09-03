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
  variants: FlagVariant[];
}

export interface FlagRule {
  /** Empty when the rule matches everyone. */
  conditions: FlagCondition[];
  /** Rollout percentage within the matched audience. */
  share: number;
  result: FlagResult;
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

const OPERATORS: Record<string, string> = {
  exact: "is",
  is_not: "is not",
  icontains: "contains",
  not_icontains: "does not contain",
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
  const groups = conditionGroups(flag);
  const ids = new Set<string>();
  for (const group of groups) {
    for (const property of group.properties) {
      if (!isDistinctIdFilter(property)) continue;
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
    const groupIndex =
      group.aggregation_group_type_index ?? flagLevelGroupIndex;
    return {
      properties: Array.isArray(group.properties)
        ? group.properties.filter(isRecord)
        : [],
      rollout,
      variant: asString(group.variant),
      isGroup: typeof groupIndex === "number",
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
      operator: OPERATORS[operatorKey ?? "in"] ?? "in cohort",
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
      operator: OPERATORS[operatorKey ?? "exact"] ?? "is",
      values,
    };
  }
  const key = asString(property.key);
  if (!key) return null;
  return {
    subject: key,
    operator: OPERATORS[operatorKey ?? "exact"] ?? operatorKey ?? "is",
    values,
  };
}

interface Audience {
  /** "one person", "25% of Power users" */
  label: string;
  plural: boolean;
}

function describeAudience(
  rule: FlagRule,
  group: ConditionGroup,
  people: Map<string, ResolvedPerson>,
): Audience {
  const noun = group.isGroup ? "groups" : "people";
  const share = rule.share < 100 ? `${rule.share}% of ` : "";
  if (rule.conditions.length === 0) {
    return rule.share < 100
      ? { label: `${rule.share}% of ${noun}`, plural: true }
      : { label: "everyone", plural: true };
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
        return {
          label: `${share}${person ? person.name : "one person"}`,
          plural: false,
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

  const matchResult = (variant: string | null): FlagResult => {
    if (isRemoteConfig) return { kind: "payload" };
    if (variant) return { kind: "variant", key: variant };
    if (variants.length > 0) return { kind: "split" };
    return { kind: "true" };
  };

  const rules: FlagRule[] = groups.map((group) => ({
    conditions: group.properties.flatMap((property) => {
      const condition = shapeCondition(property, group.isGroup, people);
      return condition ? [condition] : [];
    }),
    share: group.rollout,
    result: matchResult(group.variant),
  }));
  const fallback: FlagResult = { kind: "false" };

  if (disabled) {
    return {
      headline: "Off for everyone.",
      summary: "The flag is disabled, so every check returns false.",
      disabled,
      rules,
      fallback,
      variants,
    };
  }

  if (rules.length === 0) {
    // No condition sets means every check matches; show that as one rule so
    // the table still reads top to bottom.
    rules.push({ conditions: [], share: 100, result: matchResult(null) });
    return {
      headline: isRemoteConfig
        ? "Sends a payload to everyone."
        : variants.length > 0
          ? `Split into ${variants.length} variants for everyone.`
          : "On for everyone.",
      summary: isRemoteConfig
        ? "Every check returns the configured payload."
        : variants.length > 0
          ? "Every check returns a variant, picked by a stable hash of the distinct ID."
          : "Every check returns true.",
      disabled,
      rules,
      fallback,
      variants,
    };
  }

  const live = rules.filter((rule) => rule.share > 0);
  if (live.length === 0) {
    return {
      headline: "On for nobody yet.",
      summary:
        "Rules are defined, but rollout is 0%, so every check returns false.",
      disabled,
      rules,
      fallback,
      variants,
    };
  }

  const audiences = live.map((rule) =>
    describeAudience(rule, groups[rules.indexOf(rule)], people),
  );
  const who = joinAudiences(audiences.map((audience) => audience.label));
  const headline = isRemoteConfig
    ? `Sends a payload to ${who}.`
    : variants.length > 0
      ? `Split into ${variants.length} variants for ${who}.`
      : `On for ${who}.`;

  const sentences = live.slice(0, 2).map((rule, index) => {
    const audience = audiences[index];
    return `${capitalize(audience.label)} ${audience.plural ? "get" : "gets"} ${describeResult(rule.result)}.`;
  });
  if (live.length > 2) {
    const more = live.length - 2;
    sentences.push(
      `${more} more ${more === 1 ? "rule applies" : "rules apply"}.`,
    );
  }
  sentences.push("Everyone else gets false.");

  return {
    headline,
    summary: sentences.join(" "),
    disabled,
    rules,
    fallback,
    variants,
  };
}

/** Short "Reach" label for the stat strip: "1 person", "25% of a cohort", "Everyone". */
export function flagReachLabel(audience: FlagAudience): string {
  if (audience.disabled) return "Nobody";
  const match = audience.headline.match(/(?:for|to) (.+)\.$/);
  if (!match) return "Everyone";
  return capitalize(match[1]);
}
