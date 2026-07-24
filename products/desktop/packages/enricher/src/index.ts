// ── Detection API (replaces posthog-vscode tree-sitter service) ──

export { PostHogDetector } from "./detector.js";
export {
  classifyFlagType,
  extractConditionCount,
  extractRollout,
  extractVariants,
  isFullyRolledOut,
} from "./flag-classification.js";
export type { LangFamily, QueryStrings } from "./languages.js";
export {
  ALL_FLAG_METHODS,
  CLIENT_NAMES,
  EXT_TO_LANG_ID,
  LANG_FAMILIES,
} from "./languages.js";
export type { DetectorLogger } from "./log.js";
export { setLogger } from "./log.js";
export {
  classifyStaleness,
  STALENESS_ORDER,
} from "./stale-flags.js";

export type {
  DetectionConfig,
  EventDefinition,
  Experiment,
  ExperimentMetric,
  FeatureFlag,
  FlagAssignment,
  FlagType,
  FunctionInfo,
  ImportEdge,
  LocalWrapper,
  ParseContext,
  PostHogCall,
  PostHogInitCall,
  StalenessCheckOptions,
  StalenessReason,
  SupportedLanguage,
  VariantBranch,
  WrapperClassification,
} from "./types.js";
export { DEFAULT_CONFIG } from "./types.js";

// ── Enricher API ──

export { EnrichedResult } from "./enriched-result.js";
export { PostHogEnricher } from "./enricher.js";
export { ParseResult } from "./parse-result.js";
export { PostHogApi } from "./posthog-api.js";

export type {
  CapturedEvent,
  EnrichedEvent,
  EnrichedFlag,
  EnrichedListItem,
  EnricherApiConfig,
  EventStats,
  FlagCheck,
  ListItem,
} from "./types.js";

// ── Shared enrichment pipeline ──

export type {
  EnrichSourceApiConfig,
  EnrichSourceOptions,
} from "./enrich-source.js";
export { enrichSource } from "./enrich-source.js";

// ── Serialisation (tRPC/IPC boundary) ──

export type {
  SerializedEnrichment,
  SerializedEvent,
  SerializedEventOccurrence,
  SerializedFlag,
  SerializedFlagExperiment,
  SerializedFlagOccurrence,
  SerializedFlagVariant,
} from "./serialize.js";
export { toSerializable } from "./serialize.js";
