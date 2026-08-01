// ── Detection result types ──

export interface PostHogCall {
  method: string;
  key: string;
  line: number;
  keyStartCol: number;
  keyEndCol: number;
  /** True when the first argument is a non-literal expression (ternary, variable, etc.) */
  dynamic?: boolean;
  /** Name of the user-defined wrapper function this call was synthesized from, if any. */
  viaWrapper?: string;
  /** True when the call sits inside a JSX element so `//` comments aren't valid on its line. */
  inJsx?: boolean;
}

export interface FunctionInfo {
  name: string;
  params: string[];
  isComponent: boolean;
  bodyLine: number;
  bodyEndLine: number;
  bodyIndent: string;
}

// ── Wrapper detection ──

export type WrapperClassification =
  | { kind: "fixed-key"; key: string }
  | { kind: "pass-through"; paramIndex: number };

export interface LocalWrapper {
  /** Function name as defined (e.g. `track`). */
  name: string;
  /** Whether this wrapper calls a capture method or a flag method. */
  methodKind: "capture" | "flag";
  /** The underlying PostHog SDK method (`capture`, `getFeatureFlag`, `isFeatureEnabled`, …). */
  posthogMethod: string;
  classification: WrapperClassification;
  isDefaultExport?: boolean;
  isNamedExport?: boolean;
}

// ── Parse context ──

/**
 * Optional context threaded into `findPostHogCalls` so the caller can inject
 * cross-file wrapper knowledge without turning the detector into an I/O layer.
 */
export interface ParseContext {
  /** Wrappers keyed by the local identifier they appear as in the caller file. */
  wrappersByLocalName?: Map<string, LocalWrapper>;
  /** `import * as ns from "..."` → `Map<methodName, wrapper>` per namespace. */
  namespaceWrappers?: Map<string, Map<string, LocalWrapper>>;
}

// ── Import resolution ──

export interface ImportEdge {
  /** Local identifier in the importing file. */
  localName: string;
  /** Original exported name from the source module (same as localName unless aliased). */
  importedName: string;
  isDefault?: boolean;
  isNamespace?: boolean;
  /** Absolute path of the resolved source file, or `null` if resolution failed. */
  resolvedAbsPath: string | null;
}

export interface VariantBranch {
  flagKey: string;
  variantKey: string;
  conditionLine: number;
  startLine: number;
  endLine: number;
}

export interface FlagAssignment {
  varName: string;
  method: string;
  flagKey: string;
  line: number;
  varNameEndCol: number;
  hasTypeAnnotation: boolean;
}

export interface PostHogInitCall {
  token: string;
  tokenLine: number;
  tokenStartCol: number;
  tokenEndCol: number;
  apiHost: string | null;
  configProperties: Map<string, string>;
}

// ── Detection configuration ──

export interface DetectionConfig {
  additionalClientNames: string[];
  additionalFlagFunctions: string[];
  detectNestedClients: boolean;
  onError?: (message: string, error?: unknown) => void;
}

export const DEFAULT_CONFIG: DetectionConfig = {
  additionalClientNames: [],
  additionalFlagFunctions: [],
  detectNestedClients: true,
};

// ── Supported languages ──

export type SupportedLanguage =
  | "javascript"
  | "javascriptreact"
  | "typescript"
  | "typescriptreact"
  | "python"
  | "go"
  | "ruby";

// ── PostHog entity types (for flag classification / stale detection) ──

export interface FeatureFlag {
  id: number;
  key: string;
  name: string;
  active: boolean;
  filters: Record<string, unknown>;
  created_at: string;
  created_by: { email: string; first_name: string } | null;
  deleted: boolean;
}

export interface Experiment {
  id: number;
  name: string;
  description: string | null;
  start_date: string | null;
  end_date: string | null;
  feature_flag_key: string;
  created_at: string;
  created_by: { email: string; first_name: string } | null;
  metrics?: ExperimentMetric[];
  metrics_secondary?: ExperimentMetric[];
  parameters?: {
    feature_flag_variants?: { key: string; rollout_percentage: number }[];
    recommended_sample_size?: number;
  };
  conclusion?:
    | "won"
    | "lost"
    | "inconclusive"
    | "stopped_early"
    | "invalid"
    | null;
  conclusion_comment?: string | null;
}

export interface ExperimentMetric {
  name: string;
  metric_type: "funnel" | "mean" | "ratio" | "retention";
  goal: "increase" | "decrease";
  uuid: string;
}

export interface EventDefinition {
  id: string;
  name: string;
  description?: string | null;
  tags: string[];
  last_seen_at: string | null;
  verified?: boolean;
  hidden?: boolean;
}

// ── Stale flag types ──

import type { FlagType, StalenessReason } from "@posthog/shared";
export type { FlagType, StalenessReason };

// ── Enricher types ──

export interface CapturedEvent {
  name: string;
  line: number;
  keyStartCol: number;
  keyEndCol: number;
  dynamic: boolean;
  viaWrapper?: string;
  inJsx?: boolean;
}

export interface FlagCheck {
  method: string;
  flagKey: string;
  line: number;
  keyStartCol: number;
  keyEndCol: number;
  viaWrapper?: string;
  inJsx?: boolean;
}

export interface ListItem {
  type: "event" | "flag" | "init";
  line: number;
  name: string;
  method: string;
  detail?: string;
  viaWrapper?: string;
  inJsx?: boolean;
}

export interface EnrichedListItem extends ListItem {
  flagType?: FlagType;
  staleness?: StalenessReason | null;
  rollout?: number | null;
  active?: boolean;
  url?: string | null;
  evaluations?: number;
  evaluationUsers?: number;
  experimentName?: string | null;
  experimentStatus?: "running" | "complete" | null;
  verified?: boolean;
  description?: string | null;
  volume?: number;
  uniqueUsers?: number;
  lastSeenAt?: string | null;
  tags?: string[];
}

export interface EventStats {
  volume?: number;
  uniqueUsers?: number;
  lastSeenAt?: string | null;
}

export interface FlagEvaluationStats {
  evaluations: number;
  uniqueUsers: number;
  windowDays: number;
}

export interface EnrichmentContext {
  flags?: Map<string, FeatureFlag>;
  experiments?: Experiment[];
  eventDefinitions?: Map<string, EventDefinition>;
  eventStats?: Map<string, EventStats>;
  flagEvaluationStats?: Map<string, FlagEvaluationStats>;
  flagEvaluationStatsError?: boolean;
  flagUrls?: Map<string, string>;
  stalenessOptions?: StalenessCheckOptions;
}

export interface StalenessCheckOptions {
  staleFlagAgeDays?: number;
}

export interface EnrichedFlag {
  flagKey: string;
  occurrences: FlagCheck[];
  flag: FeatureFlag | undefined;
  flagType: FlagType;
  staleness: StalenessReason | null;
  rollout: number | null;
  variants: { key: string; rollout_percentage: number }[];
  experiment: Experiment | undefined;
  url: string | null;
  evaluationStats: FlagEvaluationStats | undefined;
  evaluationStatsError: boolean;
}

export interface EnrichedEvent {
  eventName: string;
  occurrences: CapturedEvent[];
  definition: EventDefinition | undefined;
  verified: boolean;
  lastSeenAt: string | null;
  tags: string[];
  stats: EventStats | undefined;
}

// ── API configuration ──

export interface EnricherApiConfig {
  apiKey: string;
  host: string;
  projectId: number;
  /** Timeout in ms for each API request (default: 10 000). */
  timeoutMs?: number;
}
